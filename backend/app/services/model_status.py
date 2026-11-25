"""
Estado del motor de inferencia dentro de la respuesta de `GET /models` (BUG-10, KIKE-10).

El ciclo de vida del motor (`InferenceEngineLifecycle`, E02) es único para todo
el proceso, así que el mismo estado se repite en cada elemento de la lista. Se
conserva la forma `list[ModelInfo]` de la respuesta para no romper a los
clientes existentes; solo se AGREGAN campos.

Campos agregados a cada modelo:
  engine_state  "not_initialized" | "loading" | "available" | "error" | "closed"
  engine_ready  True solo si el motor está en "available"
  engine_error  mensaje genérico cuando engine_state == "error"; el detalle
                real queda en el log del servidor (mismo criterio que BUG-19).
"""

from __future__ import annotations

from typing import Any

from app.services.inference_lifecycle import LifecycleState, LifecycleStatus

ENGINE_ERROR_DETAIL = (
    "El motor de inferencia no pudo iniciarse. Consulte los registros del servidor."
)


def with_engine_status(
    models: list[dict[str, Any]], status: LifecycleStatus
) -> list[dict[str, Any]]:
    """Devuelve copias de `models` con el estado del motor agregado."""
    state = status.state
    ready = state is LifecycleState.AVAILABLE
    error = ENGINE_ERROR_DETAIL if state is LifecycleState.ERROR else None
    output = []
    for model in models:
        item = dict(model)
        item["engine_state"] = state.value
        item["engine_ready"] = ready
        item["engine_error"] = error
        output.append(item)
    return output
