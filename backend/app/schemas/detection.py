"""
Modelos de datos normalizados para detecciones y resultados de
inferencia (E05).

Independientes de la salida nativa de cualquier motor: no importan nada
de `app.services.inference_engine` (E01) ni de ningún backend de ML.
Las coordenadas de caja son fracciones del tamaño de la imagen (0 a 1),
no píxeles — así el mismo resultado es válido sin importar la
resolución del frame de origen.

Distinción importante con `InferenceResult` (E01, en
`inference_engine.py`): aquel es la envoltura genérica y poco tipada
(`items: list[dict]`) que usa el motor internamente para devolver
cualquier tipo de predicción. `DetectionResult` (aquí) es el contrato
normalizado y fuertemente tipado pensado para cruzar esa frontera —
hacia streaming, persistencia o cualquier otro consumidor — sin que
ninguno de ellos necesite conocer la estructura nativa del motor ni del
backend que la produjo.

Todos los modelos son inmutables (`frozen=True`) y no aceptan campos
adicionales (`extra="forbid"`), para que la validación sea explícita y
la serialización estable.

[Corrección tras revisión técnica] `DetectionResult.camera_id` SÍ se
valida contra `app.core.config.get_settings().camera_id` — la única
cámara configurada para el alcance vigente del proyecto. La primera
versión de este módulo no hacía esta validación (se interpretó la nota
del contrato como alcance informativo); la revisión confirmó que el
contrato de Jira exige rechazar explícitamente cualquier otro valor.
Esto acopla este módulo a `app.core.config`, pero no al módulo de
cámara en sí (`camera_service.py`, `CameraCapture`, etc.) — se lee
únicamente un valor de configuración ya centralizado y usado en todo
el proyecto, lo mismo que hacen `inference.py` o `stream.py`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import get_settings


class NormalizedBoundingBox(BaseModel):
    """
    Caja delimitadora normalizada: cada coordenada es una fracción del
    ancho/alto de la imagen, en el intervalo [0, 1]. Independiente de la
    resolución del frame de origen.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    x_min: float = Field(
        ..., ge=0.0, le=1.0, description="Borde izquierdo, fracción del ancho (0 a 1)."
    )
    y_min: float = Field(
        ..., ge=0.0, le=1.0, description="Borde superior, fracción del alto (0 a 1)."
    )
    x_max: float = Field(
        ..., ge=0.0, le=1.0, description="Borde derecho, fracción del ancho (0 a 1)."
    )
    y_max: float = Field(
        ..., ge=0.0, le=1.0, description="Borde inferior, fracción del alto (0 a 1)."
    )

    @model_validator(mode="after")
    def _check_not_inverted_or_degenerate(self) -> "NormalizedBoundingBox":
        """
        Rechaza cajas invertidas (x_min >= x_max, o y_min >= y_max).

        Nota: se rechaza también el caso de ancho/alto exactamente cero
        (x_min == x_max), no solo el invertido (x_min > x_max) — una
        caja sin área no es una detección útil y casi siempre indica un
        error upstream. Si el equipo prefiere permitir área cero, este
        es el único lugar que habría que relajar.
        """
        if self.x_min >= self.x_max:
            raise ValueError(
                "x_min debe ser menor que x_max (caja invertida o de ancho cero)."
            )
        if self.y_min >= self.y_max:
            raise ValueError(
                "y_min debe ser menor que y_max (caja invertida o de alto cero)."
            )
        return self


class Detection(BaseModel):
    """Una detección individual normalizada, independiente del motor que la produjo."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    class_id: int = Field(
        ..., ge=0, description="Identificador numérico de la clase, según el modelo que la produjo."
    )
    label: str = Field(
        ..., min_length=1, description="Nombre legible de la clase (p. ej. 'persona', 'tornillo')."
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confianza de la detección, de 0 (nula) a 1 (máxima)."
    )
    bbox: NormalizedBoundingBox


class DetectionResult(BaseModel):
    """
    Resultado normalizado de una inferencia sobre un frame, listo para
    transmitir o persistir sin que el consumidor conozca nada del motor
    ni del backend que lo produjo.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    camera_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Identificador de la cámara origen del frame. Debe coincidir "
            "exactamente con la única cámara configurada "
            "(app.core.config.Settings.camera_id) para el alcance vigente "
            "del proyecto; cualquier otro valor se rechaza."
        ),
    )
    timestamp: float = Field(
        ...,
        ge=0.0,
        description="Marca de tiempo de la inferencia, en segundos desde epoch Unix (equivalente a time.time()).",
    )
    model_name: str = Field(
        ..., min_length=1, description="Nombre del modelo que produjo el resultado."
    )
    model_version: str = Field(
        ..., min_length=1, description="Versión del modelo que produjo el resultado."
    )
    duration_ms: float = Field(
        ..., ge=0.0, description="Duración de la inferencia, en milisegundos."
    )
    detections: list[Detection] = Field(
        default_factory=list,
        description="Detecciones encontradas; lista vacía si no se detectó nada (resultado igualmente válido).",
    )

    @model_validator(mode="after")
    def _check_camera_id_matches_configured(self) -> "DetectionResult":
        configured = get_settings().camera_id
        if self.camera_id != configured:
            raise ValueError(
                f"camera_id '{self.camera_id}' no coincide con la única "
                f"cámara configurada ('{configured}')."
            )
        return self
