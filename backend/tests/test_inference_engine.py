"""
Pruebas del contrato `InferenceEngine` (E01), usando exclusivamente
`SimulatedInferenceEngine`. No cargan ningún modelo real ni requieren
cámara física — ambas cosas están fuera del alcance de esta interfaz.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.inference_engine import (
    EngineLoadError,
    EngineNotLoadedError,
    EnginePredictionError,
    EngineState,
    InferenceResult,
    SimulatedInferenceEngine,
)


@pytest.fixture
def frame() -> np.ndarray:
    """Un frame BGR mínimo válido (10x10 px, 3 canales)."""
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_carga_correcta_transiciona_a_loaded():
    engine = SimulatedInferenceEngine()

    assert engine.get_status().state == EngineState.UNLOADED

    engine.load()

    status = engine.get_status()
    assert status.state == EngineState.LOADED
    assert status.loaded_at is not None
    assert status.last_error is None


def test_load_es_idempotente():
    engine = SimulatedInferenceEngine()

    engine.load()
    first_loaded_at = engine.get_status().loaded_at

    engine.load()  # segunda llamada: no debe fallar ni "recargar"

    assert engine.get_status().state == EngineState.LOADED
    assert engine.get_status().loaded_at == first_loaded_at


def test_prediccion_simulada_devuelve_resultado_tipado(frame):
    engine = SimulatedInferenceEngine(model_id="sim-1", task="localization")
    engine.load()

    result = engine.predict(frame)

    assert isinstance(result, InferenceResult)
    assert result.task == "localization"
    assert result.model_id == "sim-1"
    assert len(result.items) == 1
    assert result.items[0]["class_name"] == "objeto_simulado"
    assert result.score is None  # solo "anomaly" trae score


def test_prediccion_simulada_tarea_anomaly_incluye_score(frame):
    engine = SimulatedInferenceEngine(task="anomaly")
    engine.load()

    result = engine.predict(frame)

    assert result.score is not None


def test_uso_invalido_antes_de_cargar(frame):
    engine = SimulatedInferenceEngine()

    with pytest.raises(EngineNotLoadedError):
        engine.predict(frame)


def test_uso_invalido_despues_de_cerrar(frame):
    engine = SimulatedInferenceEngine()
    engine.load()
    engine.close()

    with pytest.raises(EngineNotLoadedError):
        engine.predict(frame)


def test_prediccion_con_frame_invalido_lanza_error_tipado():
    engine = SimulatedInferenceEngine()
    engine.load()

    with pytest.raises(EnginePredictionError):
        engine.predict(np.array([]))  # frame vacío


def test_cierre_idempotente_sin_haber_cargado():
    engine = SimulatedInferenceEngine()

    engine.close()  # no debe lanzar, aunque nunca se llamó load()

    assert engine.get_status().state == EngineState.UNLOADED


def test_cierre_idempotente_llamado_dos_veces(frame):
    engine = SimulatedInferenceEngine()
    engine.load()

    engine.close()
    engine.close()  # segunda llamada: no debe fallar

    assert engine.get_status().state == EngineState.UNLOADED


def test_consulta_de_estado_en_cada_fase(frame):
    engine = SimulatedInferenceEngine()

    assert engine.get_status().state == EngineState.UNLOADED

    engine.load()
    assert engine.get_status().state == EngineState.LOADED

    engine.close()
    assert engine.get_status().state == EngineState.UNLOADED


def test_fallo_de_carga_transiciona_a_error_y_registra_causa():
    engine = SimulatedInferenceEngine(fail_on_load=True)

    with pytest.raises(EngineLoadError):
        engine.load()

    status = engine.get_status()
    assert status.state == EngineState.ERROR
    assert status.last_error is not None
