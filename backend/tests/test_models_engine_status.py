"""
Pruebas del estado del motor en `GET /models` — BUG-10 (KIKE-10).

QA: `GET /models` respondía igual con el motor disponible que apagado, porque
ningún endpoint consultaba el ciclo de vida (E02). Ahora cada modelo incluye
`engine_state`, `engine_ready` y `engine_error`.

Cada prueba usa su PROPIA instancia de `InferenceEngineLifecycle`; el singleton
`inference_lifecycle` de la aplicación no se toca.
"""

from __future__ import annotations

import asyncio

from app.services.inference_engine import SimulatedInferenceEngine
from app.services.inference_lifecycle import InferenceEngineLifecycle, LifecycleState, LifecycleStatus
from app.services.model_status import ENGINE_ERROR_DETAIL, with_engine_status

MODELOS = [
    {"id": "a", "task": "localization", "backend": "ultralytics", "available": True, "loaded": False},
    {"id": "b", "task": "ocr", "backend": "paddleocr", "available": True, "loaded": True},
]


def status(state: LifecycleState, error: str | None = None) -> LifecycleStatus:
    return LifecycleStatus(state=state, loaded_at=None, last_error=error)


def test_motor_disponible_se_reporta_listo():
    salida = with_engine_status(MODELOS, status(LifecycleState.AVAILABLE))
    assert [m["engine_state"] for m in salida] == ["available", "available"]
    assert all(m["engine_ready"] is True for m in salida)
    assert all(m["engine_error"] is None for m in salida)


def test_motor_apagado_se_reporta_cerrado_y_no_listo():
    salida = with_engine_status(MODELOS, status(LifecycleState.CLOSED))
    assert all(m["engine_state"] == "closed" for m in salida)
    assert all(m["engine_ready"] is False for m in salida)


def test_motor_en_error_reporta_mensaje_generico_sin_el_detalle_interno():
    detalle = "No se pudo cargar C:\\modelos\\privado\\yolo.pt"
    salida = with_engine_status(MODELOS, status(LifecycleState.ERROR, detalle))
    assert all(m["engine_state"] == "error" for m in salida)
    assert all(m["engine_ready"] is False for m in salida)
    assert all(m["engine_error"] == ENGINE_ERROR_DETAIL for m in salida)
    assert "privado" not in str(salida)


def test_estados_intermedios():
    for estado in (LifecycleState.NOT_INITIALIZED, LifecycleState.LOADING):
        salida = with_engine_status(MODELOS, status(estado))
        assert salida[0]["engine_state"] == estado.value
        assert salida[0]["engine_ready"] is False
        assert salida[0]["engine_error"] is None


def test_no_modifica_la_lista_original_ni_quita_campos():
    original = [dict(m) for m in MODELOS]
    salida = with_engine_status(MODELOS, status(LifecycleState.AVAILABLE))
    assert MODELOS == original
    for antes, despues in zip(MODELOS, salida):
        assert all(despues[k] == v for k, v in antes.items())


def test_el_estado_cambia_con_el_ciclo_de_vida_real():
    # El escenario exacto del reporte: GET /models, shutdown(), GET /models.
    async def escenario() -> list[str]:
        ciclo = InferenceEngineLifecycle(SimulatedInferenceEngine())
        vistos = [with_engine_status(MODELOS, ciclo.get_status())[0]["engine_state"]]
        await ciclo.initialize()
        vistos.append(with_engine_status(MODELOS, ciclo.get_status())[0]["engine_state"])
        await ciclo.shutdown()
        vistos.append(with_engine_status(MODELOS, ciclo.get_status())[0]["engine_state"])
        return vistos

    assert asyncio.run(escenario()) == ["not_initialized", "available", "closed"]
