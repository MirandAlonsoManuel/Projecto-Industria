"""
Pruebas de los modelos normalizados de detección (E05). No requieren
modelo real ni cámara física — son modelos de datos puros (pydantic).
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.detection import Detection, DetectionResult, NormalizedBoundingBox


def _bbox(**overrides) -> dict:
    base = {"x_min": 0.1, "y_min": 0.1, "x_max": 0.5, "y_max": 0.6}
    base.update(overrides)
    return base


def _detection(**overrides) -> dict:
    base = {
        "class_id": 0,
        "label": "persona",
        "confidence": 0.9,
        "bbox": _bbox(),
    }
    base.update(overrides)
    return base


def _result(**overrides) -> dict:
    # Usa la cámara realmente configurada, en vez de un literal fijo,
    # para que estas pruebas no dependan de adivinar el valor por
    # defecto de Settings.camera_id.
    base = {
        "camera_id": get_settings().camera_id,
        "timestamp": 1_700_000_000.0,
        "model_name": "yolo-industrial",
        "model_version": "1.2.0",
        "duration_ms": 42.5,
        "detections": [_detection()],
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────
# Casos válidos
# ─────────────────────────────────────────────────────────────────────────


def test_bbox_valida():
    bbox = NormalizedBoundingBox(**_bbox())
    assert bbox.x_min == 0.1
    assert bbox.y_max == 0.6


def test_bbox_limites_inclusive_0_y_1_son_validos():
    bbox = NormalizedBoundingBox(x_min=0.0, y_min=0.0, x_max=1.0, y_max=1.0)
    assert bbox.x_min == 0.0
    assert bbox.x_max == 1.0


def test_deteccion_valida():
    detection = Detection(**_detection())
    assert detection.label == "persona"
    assert isinstance(detection.bbox, NormalizedBoundingBox)


def test_confianza_limites_0_y_1_son_validas():
    Detection(**_detection(confidence=0.0))
    Detection(**_detection(confidence=1.0))


def test_resultado_valido_con_detecciones():
    result = DetectionResult(**_result())
    assert len(result.detections) == 1
    assert result.camera_id == "0"


def test_resultado_valido_sin_detecciones_lista_vacia():
    result = DetectionResult(**_result(detections=[]))
    assert result.detections == []


def test_duration_cero_es_valida():
    DetectionResult(**_result(duration_ms=0.0))


def test_timestamp_cero_es_valido():
    DetectionResult(**_result(timestamp=0.0))


# ─────────────────────────────────────────────────────────────────────────
# Caja: coordenadas fuera de rango
# ─────────────────────────────────────────────────────────────────────────


def test_bbox_coordenada_menor_que_cero_rechazada():
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(**_bbox(x_min=-0.01))


def test_bbox_coordenada_mayor_que_uno_rechazada():
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(**_bbox(y_max=1.01))


# ─────────────────────────────────────────────────────────────────────────
# Caja: invertida o degenerada
# ─────────────────────────────────────────────────────────────────────────


def test_bbox_invertida_en_x_rechazada():
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(**_bbox(x_min=0.6, x_max=0.2))


def test_bbox_invertida_en_y_rechazada():
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(**_bbox(y_min=0.8, y_max=0.3))


def test_bbox_ancho_cero_rechazada():
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(**_bbox(x_min=0.3, x_max=0.3))


def test_bbox_alto_cero_rechazada():
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(**_bbox(y_min=0.3, y_max=0.3))


# ─────────────────────────────────────────────────────────────────────────
# Detección: confianza y campos inválidos
# ─────────────────────────────────────────────────────────────────────────


def test_confianza_negativa_rechazada():
    with pytest.raises(ValidationError):
        Detection(**_detection(confidence=-0.1))


def test_confianza_mayor_que_uno_rechazada():
    with pytest.raises(ValidationError):
        Detection(**_detection(confidence=1.1))


def test_class_id_negativo_rechazado():
    with pytest.raises(ValidationError):
        Detection(**_detection(class_id=-1))


def test_label_vacio_rechazado():
    with pytest.raises(ValidationError):
        Detection(**_detection(label=""))


# ─────────────────────────────────────────────────────────────────────────
# Resultado: tiempos negativos y campos obligatorios ausentes
# ─────────────────────────────────────────────────────────────────────────


def test_duration_negativa_rechazada():
    with pytest.raises(ValidationError):
        DetectionResult(**_result(duration_ms=-1.0))


def test_timestamp_negativo_rechazado():
    with pytest.raises(ValidationError):
        DetectionResult(**_result(timestamp=-1.0))


def test_camera_id_vacio_rechazado():
    with pytest.raises(ValidationError):
        DetectionResult(**_result(camera_id=""))


def test_camera_id_distinto_al_configurado_rechazado():
    configured = get_settings().camera_id
    otro_id = configured + "-otro"  # garantiza que sea distinto al configurado

    with pytest.raises(ValidationError):
        DetectionResult(**_result(camera_id=otro_id))


def test_camera_id_igual_al_configurado_es_valido(monkeypatch):
    monkeypatch.setenv("CAMERA_ID", "camara-de-prueba")
    get_settings.cache_clear()

    result = DetectionResult(**_result(camera_id="camara-de-prueba"))

    assert result.camera_id == "camara-de-prueba"


def test_camera_id_distinto_al_configurado_rechazado_con_override(monkeypatch):
    monkeypatch.setenv("CAMERA_ID", "camara-de-prueba")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        DetectionResult(**_result(camera_id="otra-camara-cualquiera"))


def test_campo_obligatorio_ausente_en_bbox_rechazado():
    bbox_incompleta = _bbox()
    del bbox_incompleta["y_max"]
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(**bbox_incompleta)


def test_campo_obligatorio_ausente_en_resultado_rechazado():
    resultado_incompleto = _result()
    del resultado_incompleto["model_version"]
    with pytest.raises(ValidationError):
        DetectionResult(**resultado_incompleto)


def test_campo_extra_no_declarado_rechazado():
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(**_bbox(z_min=0.0))


# ─────────────────────────────────────────────────────────────────────────
# Serialización estable
# ─────────────────────────────────────────────────────────────────────────


def test_serializacion_lista_vacia_en_json():
    result = DetectionResult(**_result(detections=[]))
    data = json.loads(result.model_dump_json())
    assert data["detections"] == []


def test_round_trip_json_preserva_el_valor():
    original = DetectionResult(**_result())
    reconstructed = DetectionResult.model_validate_json(original.model_dump_json())
    assert reconstructed == original


def test_serializacion_incluye_todos_los_campos_del_contrato():
    result = DetectionResult(**_result())
    data = result.model_dump()
    assert set(data.keys()) == {
        "camera_id",
        "timestamp",
        "model_name",
        "model_version",
        "duration_ms",
        "detections",
    }
