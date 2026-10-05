"""
Ciclo de vida del servicio de inferencia (E02).

Envuelve un `InferenceEngine` (ver inference_engine.py, E01) y le agrega
las garantías que la aplicación necesita a nivel de proceso: el motor se
carga una sola vez aunque se solicite la inicialización repetidamente
(incluyendo llamadas concurrentes), su estado es consultable con una
granularidad más fina que la del motor, y el cierre es idempotente y
libera recursos sin importar si se llega a él por un cierre normal, una
excepción durante la carga, o una cancelación.

Pensado para engancharse al lifespan de FastAPI: `initialize()` en el
arranque, `shutdown()` en el cierre. Esta capa es agnóstica de qué
`InferenceEngine` concreto envuelve — en este ticket se conecta
exclusivamente con `SimulatedInferenceEngine` (E01); conectar un motor
real es trabajo de una tarea posterior.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.services.inference_engine import InferenceEngine

logger = logging.getLogger(__name__)


class LifecycleState(str, Enum):
    """
    Estado del ciclo de vida del SERVICIO de inferencia — no confundir
    con `EngineState` de E01, que describe solo al motor (unloaded /
    loaded / error). Este estado agrega las dos fases que la aplicación
    necesita y que el motor no expone: una transitoria de carga
    (`LOADING`) y una terminal de apagado (`CLOSED`).
    """

    NOT_INITIALIZED = "not_initialized"
    LOADING = "loading"
    AVAILABLE = "available"
    ERROR = "error"
    CLOSED = "closed"


@dataclass(frozen=True)
class LifecycleStatus:
    """Snapshot consultable sin efectos secundarios, válido en cualquier estado."""

    state: LifecycleState
    loaded_at: Optional[float]
    last_error: Optional[str]


class InferenceEngineLifecycle:
    """
    Administra el ciclo de vida de un único `InferenceEngine` para todo
    el proceso.

    Garantías de comportamiento:
      - `initialize()` carga el motor una sola vez, incluso si se llama
        repetidamente o de forma concurrente (protegido por un lock).
      - `initialize()` llamado en estado `ERROR` reintenta la carga
        (permite recuperación manual sin recrear la instancia).
      - `initialize()` llamado en estado `CLOSED` lanza `RuntimeError`:
        un ciclo de vida cerrado no se reabre a sí mismo — para volver a
        operar se crea una nueva instancia (ver pruebas de "reinicio").
      - `shutdown()` es idempotente: llamarlo más de una vez, o sin
        haber inicializado nunca, no falla.
      - `shutdown()` libera el motor sin importar si se llega a él desde
        `AVAILABLE`, `ERROR`, o tras una `initialize()` cancelada.
      - `get_status()` nunca lanza; es seguro en cualquier estado.
    """

    def __init__(self, engine: InferenceEngine) -> None:
        self._engine = engine
        self._state = LifecycleState.NOT_INITIALIZED
        self._loaded_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """
        Carga el motor. Ver garantías de comportamiento en el docstring
        de la clase.

        Raises:
            RuntimeError: si el ciclo de vida ya está `CLOSED`.
            Exception: la excepción original de `engine.load()` (p. ej.
                `EngineLoadError`) si la carga falla.
        """
        async with self._lock:
            if self._state is LifecycleState.AVAILABLE:
                return  # ya cargado: no-op, garantiza carga única

            if self._state is LifecycleState.CLOSED:
                raise RuntimeError(
                    "No se puede inicializar un ciclo de vida ya cerrado; "
                    "cree una nueva instancia de InferenceEngineLifecycle."
                )

            self._state = LifecycleState.LOADING
            self._last_error = None

            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._engine.load)
            except asyncio.CancelledError:
                self._state = LifecycleState.ERROR
                self._last_error = "La inicialización fue cancelada."
                self._safe_close_engine()
                raise
            except Exception as exc:
                self._state = LifecycleState.ERROR
                self._last_error = str(exc)
                self._safe_close_engine()
                raise

            self._state = LifecycleState.AVAILABLE
            self._loaded_at = time.monotonic()

    async def shutdown(self) -> None:
        """Libera el motor y transiciona a `CLOSED`. Idempotente."""
        async with self._lock:
            if self._state is LifecycleState.CLOSED:
                return
            self._safe_close_engine()
            self._state = LifecycleState.CLOSED
            self._loaded_at = None

    def get_status(self) -> LifecycleStatus:
        """Retorna el estado actual, sin efectos secundarios."""
        return LifecycleStatus(
            state=self._state,
            loaded_at=self._loaded_at,
            last_error=self._last_error,
        )

    @property
    def engine(self) -> InferenceEngine:
        """Acceso de solo lectura al motor envuelto (p. ej. para predict())."""
        return self._engine

    def _safe_close_engine(self) -> None:
        """
        Cierra el motor sin dejar que una excepción de close() oculte la
        causa original del fallo, ni deje recursos a medio liberar.
        """
        try:
            self._engine.close()
        except Exception as exc:  # pragma: no cover - defensivo
            logger.warning("Error cerrando el motor durante la limpieza: %s", exc)
