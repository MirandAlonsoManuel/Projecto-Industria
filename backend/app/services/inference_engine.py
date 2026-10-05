"""
Interfaz común para motores de inferencia (patrón Strategy), análoga a
`CameraCapture` en `camera_service.py`: desacopla a los consumidores
(routers, streaming, persistencia) de la tecnología concreta del modelo.

Diseño: una sola interfaz genérica (`InferenceEngine`), no una por tarea.
Cada motor real (ultralytics, torchvision, paddleocr, etc.) implementaría
esta misma interfaz; aquí solo se entrega, además del contrato, un motor
*simulado* mínimo, usado exclusivamente por pruebas — ningún motor real
se construye en este módulo ni se requiere cámara física para probarlo.

Solo depende de tipos propios de este módulo, la librería estándar y
NumPy (para el frame de entrada) — sin pydantic, sin backends de ML.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import numpy as np

# ─────────────────────────────────────────────────────────────────────────
# Errores
# ─────────────────────────────────────────────────────────────────────────


class InferenceEngineError(Exception):
    """Base de todos los errores del contrato de motor de inferencia."""


class EngineLoadError(InferenceEngineError):
    """`load()` no pudo completar la carga (pesos ausentes, backend no
    disponible, configuración inválida, etc.)."""


class EngineNotLoadedError(InferenceEngineError):
    """Se invocó `predict()` (o una operación que lo requiere) sin haber
    llamado `load()` antes, o después de que el motor fue `close()`-ado."""


class EnginePredictionError(InferenceEngineError):
    """El motor está cargado, pero la predicción falló (entrada inválida
    para este motor, o excepción propagada desde el backend real)."""


# ─────────────────────────────────────────────────────────────────────────
# Estado
# ─────────────────────────────────────────────────────────────────────────


class EngineState(str, Enum):
    """Estado del ciclo de vida de un motor de inferencia."""

    UNLOADED = "unloaded"  # nunca cargado, o ya cerrado (close())
    LOADED = "loaded"  # listo para predecir
    ERROR = "error"  # load() falló; requiere un nuevo load() para recuperarse


@dataclass(frozen=True)
class EngineStatus:
    """Snapshot consultable del estado de un motor. No tiene efectos
    secundarios: `get_status()` siempre debe poder llamarse en cualquier
    estado, incluyendo UNLOADED, sin lanzar excepciones."""

    state: EngineState
    model_id: Optional[str]
    task: Optional[str]
    loaded_at: Optional[float]
    last_error: Optional[str]


# ─────────────────────────────────────────────────────────────────────────
# Resultado de predicción
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InferenceResult:
    """
    Envoltura genérica del resultado de una predicción, independiente de
    la tarea concreta. El significado de `items` depende de `task`:

      - "localization":    cada item es una detección:
                           {"class_id": int, "class_name": str,
                            "confidence": float, "bbox": [x1,y1,x2,y2]}
      - "classification":  cada item es una predicción top-k:
                           {"class_id": int, "class_name": str,
                            "confidence": float}
      - "ocr":             cada item es un resultado de texto:
                           {"text": str, "confidence": float,
                            "polygon": [[x,y], ...]}
      - "anomaly":         cada item es una región anómala:
                           {"score": float, "area": int,
                            "bbox": [x1,y1,x2,y2]}
                           (el score global de la imagen va en `score`,
                           no en los items).

    Esta forma espeja deliberadamente `list[dict[str, Any]]`, la misma
    convención que ya usa `InferenceService` en el código existente
    (`localize`, `classify`, `ocr`, `anomaly_reference`), para que una
    futura integración no tenga que inventar un mapeo nuevo.
    """

    task: str
    model_id: str
    items: list[dict[str, Any]] = field(default_factory=list)
    score: Optional[float] = None  # solo relevante para "anomaly"
    latency_ms: float = 0.0


# ─────────────────────────────────────────────────────────────────────────
# Interfaz
# ─────────────────────────────────────────────────────────────────────────


class InferenceEngine(ABC):
    """
    Contrato que debe cumplir cualquier motor de inferencia, real o
    simulado. Separa explícitamente cuatro responsabilidades:

      1. `load()`         — carga de recursos (pesos, sesión de backend).
      2. `predict()`      — ejecutar una predicción sobre un frame.
      3. `get_status()`   — consulta de estado, sin efectos secundarios.
      4. `close()`        — liberación ordenada de recursos.

    Contrato de comportamiento que toda implementación debe respetar:

      - `load()` debe ser **idempotente**: llamarlo cuando ya está
        `LOADED` no debe recargar el modelo ni lanzar error.
      - `predict()` debe lanzar `EngineNotLoadedError` si el motor no
        está `LOADED` (nunca se cargó, o ya se cerró).
      - `predict()` debe lanzar `EnginePredictionError` (no dejar pasar
        la excepción cruda del backend) ante una entrada inválida o un
        fallo del backend durante la predicción.
      - `close()` debe ser **idempotente**: llamarlo más de una vez, o
        sin haber cargado nunca, no debe lanzar error.
      - `get_status()` nunca lanza: debe poder consultarse en cualquier
        estado, incluyendo antes de `load()` y después de `close()`.
    """

    @abstractmethod
    def load(self) -> None:
        """Carga el modelo/recursos necesarios para predecir."""

    @abstractmethod
    def predict(self, frame: np.ndarray, **params: Any) -> InferenceResult:
        """
        Ejecuta una predicción sobre `frame`.

        Args:
            frame: imagen de entrada como `np.ndarray` (BGR, como la
                devuelve `image_service.decode_image`). Es el único tipo
                de frame que esta interfaz reconoce.
            **params: parámetros específicos de la tarea/backend
                (p. ej. `conf`, `iou`, `top_k`) — cada implementación
                documenta cuáles acepta.

        Returns:
            InferenceResult con el resultado tipado de la predicción.

        Raises:
            EngineNotLoadedError: si no se llamó `load()` antes.
            EnginePredictionError: si la predicción falla.
        """

    @abstractmethod
    def get_status(self) -> EngineStatus:
        """Retorna el estado actual del motor, sin efectos secundarios."""

    @abstractmethod
    def close(self) -> None:
        """Libera los recursos cargados. Debe ser idempotente."""


# ─────────────────────────────────────────────────────────────────────────
# Motor simulado — exclusivamente para pruebas
# ─────────────────────────────────────────────────────────────────────────


class SimulatedInferenceEngine(InferenceEngine):
    """
    Motor mínimo sin backend real. Úsese EXCLUSIVAMENTE en pruebas
    automatizadas — nunca en código de producción — para validar que
    cualquier consumidor que dependa de `InferenceEngine` funciona sin
    necesitar un modelo real ni hardware.

    Es determinista: ante un frame válido, siempre devuelve el mismo
    resultado fijo (una única detección simulada). Permite forzar un
    fallo de carga (`fail_on_load=True`) para probar el camino de error.
    """

    def __init__(
        self,
        model_id: str = "sim-0",
        task: str = "localization",
        fail_on_load: bool = False,
    ) -> None:
        self._model_id = model_id
        self._task = task
        self._fail_on_load = fail_on_load
        self._state = EngineState.UNLOADED
        self._loaded_at: Optional[float] = None
        self._last_error: Optional[str] = None

    def load(self) -> None:
        if self._state is EngineState.LOADED:
            return  # idempotente: ya está cargado, no hay nada que hacer

        if self._fail_on_load:
            self._state = EngineState.ERROR
            self._last_error = "Fallo simulado de carga (fail_on_load=True)."
            raise EngineLoadError(self._last_error)

        self._state = EngineState.LOADED
        self._loaded_at = time.monotonic()
        self._last_error = None

    def predict(self, frame: np.ndarray, **params: Any) -> InferenceResult:
        if self._state is not EngineState.LOADED:
            raise EngineNotLoadedError(
                "El motor no está cargado; llame load() antes de predict()."
            )

        if not isinstance(frame, np.ndarray) or frame.size == 0:
            raise EnginePredictionError(
                "El frame de entrada es inválido o está vacío."
            )

        t0 = time.monotonic()
        items = [
            {
                "class_id": 0,
                "class_name": "objeto_simulado",
                "confidence": 0.99,
                "bbox": [0.0, 0.0, 10.0, 10.0],
            }
        ]
        latency_ms = (time.monotonic() - t0) * 1000

        return InferenceResult(
            task=self._task,
            model_id=self._model_id,
            items=items,
            score=0.5 if self._task == "anomaly" else None,
            latency_ms=latency_ms,
        )

    def get_status(self) -> EngineStatus:
        return EngineStatus(
            state=self._state,
            model_id=self._model_id,
            task=self._task,
            loaded_at=self._loaded_at,
            last_error=self._last_error,
        )

    def close(self) -> None:
        # Idempotente: cerrar un motor ya cerrado (o nunca cargado) no es
        # un error — simplemente no hay nada que liberar.
        self._state = EngineState.UNLOADED
        self._loaded_at = None
