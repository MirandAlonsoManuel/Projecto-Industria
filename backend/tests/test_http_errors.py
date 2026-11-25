"""
Pruebas del mapeo de errores a HTTP — BUG-09 y BUG-19 (KIKE-8).

BUG-09: los errores del cliente no deben responderse como 503.
BUG-19: los errores del servidor no deben mostrar rutas ni detalles internos.

Se usan instancias PROPIAS de `InferenceService` / `ModelRegistry`; no se toca
el singleton `inference_service` de los demás módulos.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from app.api.http_errors import (
    INTERNAL_ERROR_DETAIL,
    SERVICE_UNAVAILABLE_DETAIL,
    to_http_error,
)
from app.services.image_service import ImageInputError
from app.services.inference_service import InferenceError, InferenceRequestError, InferenceService
from app.services.model_registry import ModelRegistry, ModelRegistryError

RUTA_INTERNA = "C:\\Users\\servidor\\.cache\\torch\\hub\\checkpoints\\modelo.pth"
DETALLE_CUDA = f"CUDA error: out of memory (libcudart 12.1) cargando {RUTA_INTERNA}"


# ------------------------------------------------------------------ BUG-09: 400

def test_inference_request_error_es_subclase_de_inference_error():
    # Compatibilidad: código existente que captura InferenceError sigue funcionando.
    assert issubclass(InferenceRequestError, InferenceError)


@pytest.mark.parametrize(
    "exc",
    [
        ImageInputError("No se pudo decodificar la imagen."),
        ModelRegistryError("Modelo no registrado: inexistente"),
        InferenceRequestError("El modelo x no corresponde a la tarea ocr."),
    ],
)
def test_errores_del_cliente_responden_400_con_su_mensaje(exc):
    http = to_http_error(exc)
    assert http.status_code == 400
    assert http.detail == str(exc)


def test_modelo_de_otra_tarea_responde_400_no_503():
    # Caso 1 del reporte: pedir a OCR un modelo de localización.
    service = InferenceService(ModelRegistry())
    with pytest.raises(InferenceRequestError) as info:
        service.ocr(np.zeros((10, 10, 3), dtype=np.uint8), "yolo26n-localization")
    assert "no corresponde a la tarea ocr" in str(info.value)
    assert to_http_error(info.value).status_code == 400


def test_modelo_inexistente_responde_400():
    service = InferenceService(ModelRegistry())
    with pytest.raises(ModelRegistryError) as info:
        service.localize(np.zeros((10, 10, 3), dtype=np.uint8), "no-existe", 0.25, 0.45)
    assert to_http_error(info.value).status_code == 400


def test_imagen_y_referencia_de_distinto_tamano_responde_400_no_503():
    # Caso 2 del reporte: /inference/anomaly con imágenes de tamaños diferentes.
    service = InferenceService(ModelRegistry())
    imagen = np.zeros((20, 20, 3), dtype=np.uint8)
    referencia = np.zeros((30, 30, 3), dtype=np.uint8)
    with pytest.raises(InferenceRequestError) as info:
        service.anomaly_reference(imagen, referencia, None, None)
    assert "mismo tamaño" in str(info.value)
    assert to_http_error(info.value).status_code == 400


def test_anomaly_con_mismo_tamano_sigue_funcionando():
    # Control: el cambio no rompe el camino feliz.
    service = InferenceService(ModelRegistry())
    imagen = np.zeros((40, 40, 3), dtype=np.uint8)
    model_id, score, regions = service.anomaly_reference(imagen, imagen.copy(), None, None)
    assert model_id == "reference-diff-v1"
    assert score == 0.0
    assert regions == []


# --------------------------------------------------------- BUG-19: sin detalles internos

def test_error_del_servidor_responde_503_generico_y_registra_el_detalle(caplog):
    exc = InferenceError(f"Falló la inferencia de localización: {DETALLE_CUDA}")
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        http = to_http_error(exc)
    assert http.status_code == 503
    assert http.detail == SERVICE_UNAVAILABLE_DETAIL
    for fragmento in ("CUDA", "libcudart", "torch", "Users", RUTA_INTERNA):
        assert fragmento not in http.detail
    # El detalle real SÍ queda disponible para quien opera el servidor.
    assert DETALLE_CUDA in caplog.text


def test_error_inesperado_responde_500_generico_y_registra_el_detalle(caplog):
    exc = RuntimeError(f"[Errno 2] No such file or directory: '{RUTA_INTERNA}'")
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        http = to_http_error(exc)
    assert http.status_code == 500
    assert http.detail == INTERNAL_ERROR_DETAIL
    assert RUTA_INTERNA not in http.detail
    assert RUTA_INTERNA in caplog.text


def test_la_causa_encadenada_tampoco_llega_al_cliente(caplog):
    try:
        try:
            raise OSError(f"no se pudo abrir {RUTA_INTERNA}")
        except OSError as causa:
            raise InferenceError("No se pudo cargar yolo26n-localization") from causa
    except InferenceError as exc:
        with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
            http = to_http_error(exc)
    assert RUTA_INTERNA not in str(http.detail)
    assert RUTA_INTERNA in caplog.text  # la traza completa sí se registra


def test_registro_de_modelos_inexistente_no_muestra_la_ruta(tmp_path, caplog):
    ruta = tmp_path / "carpeta_secreta" / "model_registry.json"
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ModelRegistryError) as info:
            ModelRegistry(ruta)
    assert "carpeta_secreta" not in str(info.value)
    assert str(tmp_path) not in str(info.value)
    assert "No existe el registro de modelos" in str(info.value)
    assert "carpeta_secreta" in caplog.text
