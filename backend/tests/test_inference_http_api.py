"""
Pruebas de extremo a extremo (HTTP real contra `create_app()`) de los bugs de
KIKE-8 y KIKE-10: BUG-09, BUG-10, BUG-18 y BUG-19.

Aislamiento: no se usa `with TestClient(...)`, así que NO se ejecuta el lifespan
y no se toca el singleton `inference_lifecycle`. El servicio y el ciclo de vida
del router se reemplazan por dobles propios con `monkeypatch`; el singleton
`inference_service` tampoco se modifica.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.api.http_errors import INTERNAL_ERROR_DETAIL, SERVICE_UNAVAILABLE_DETAIL
from app.api.routers import inference as inference_router
from app.core.config import Settings
from app.services.inference_lifecycle import LifecycleState, LifecycleStatus
from app.services.inference_service import InferenceError, InferenceService
from app.services.model_registry import ModelRegistry

LIMIT = 100_000  # bytes por imagen en estas pruebas
BOUNDARY = "frontera-http"
RUTA_INTERNA = "C:\\Users\\servidor\\.cache\\torch\\modelo.pth"


def png(width: int, height: int) -> bytes:
    ok, encoded = cv2.imencode(".png", np.zeros((height, width, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(max_upload_bytes=LIMIT))
    return TestClient(main_module.create_app())


class FakeLifecycle:
    def __init__(self, state: LifecycleState, error: str | None = None) -> None:
        self._status = LifecycleStatus(state=state, loaded_at=None, last_error=error)

    def get_status(self) -> LifecycleStatus:
        return self._status


# ------------------------------------------------------------------ BUG-18

def test_imagen_mas_grande_que_el_limite_responde_413(client):
    response = client.post(
        "/inference/localization",
        files={"image": ("grande.jpg", b"\x00" * (LIMIT * 3), "image/jpeg")},
    )
    assert response.status_code == 413
    assert "tamaño máximo" in response.json()["detail"]


def test_cuerpo_sin_content_length_mas_grande_que_el_limite_responde_413(client):
    def trozos():
        yield (
            f"--{BOUNDARY}\r\n"
            'Content-Disposition: form-data; name="image"; filename="grande.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        for _ in range(30):
            yield b"\x00" * (LIMIT // 5)
        yield f"\r\n--{BOUNDARY}--\r\n".encode()

    response = client.post(
        "/inference/localization",
        content=trozos(),
        headers={"content-type": f"multipart/form-data; boundary={BOUNDARY}"},
    )
    assert response.status_code == 413


def test_imagen_dentro_del_limite_llega_al_endpoint(client):
    # No es una imagen válida: debe llegar al endpoint y fallar ahí con 400
    # (decodificación), no ser frenada por el límite con 413.
    response = client.post(
        "/inference/localization",
        files={"image": ("ok.jpg", b"\x00" * (LIMIT - 1000), "image/jpeg")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "No se pudo decodificar la imagen."


def test_el_413_lleva_encabezados_cors(client):
    response = client.post(
        "/inference/localization",
        files={"image": ("grande.jpg", b"\x00" * (LIMIT * 3), "image/jpeg")},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_el_limite_por_defecto_es_25_mib(monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)
    assert Settings(_env_file=None).max_upload_bytes == 25 * 1024 * 1024


# ------------------------------------------------------------------ BUG-09

def test_anomaly_con_imagenes_de_distinto_tamano_responde_400(client, monkeypatch):
    monkeypatch.setattr(inference_router, "inference_service", InferenceService(ModelRegistry()))
    response = client.post(
        "/inference/anomaly",
        files={
            "image": ("a.png", png(40, 40), "image/png"),
            "reference_image": ("b.png", png(60, 60), "image/png"),
        },
    )
    assert response.status_code == 400
    assert "mismo tamaño" in response.json()["detail"]


def test_modelo_de_otra_tarea_responde_400(client, monkeypatch):
    monkeypatch.setattr(inference_router, "inference_service", InferenceService(ModelRegistry()))
    response = client.post(
        "/inference/ocr",
        params={"model_id": "yolo26n-localization"},
        files={"image": ("a.png", png(40, 40), "image/png")},
    )
    assert response.status_code == 400
    assert "no corresponde a la tarea ocr" in response.json()["detail"]


# ------------------------------------------------------------------ BUG-19

class ServicioQueFalla:
    def localize(self, *args, **kwargs):
        raise InferenceError(f"Falló la inferencia de localización: CUDA OOM cargando {RUTA_INTERNA}")


class ServicioQueExplota:
    def localize(self, *args, **kwargs):
        raise RuntimeError(f"[Errno 2] No such file or directory: '{RUTA_INTERNA}'")


def test_fallo_del_modelo_responde_503_sin_detalles_internos(client, monkeypatch):
    monkeypatch.setattr(inference_router, "inference_service", ServicioQueFalla())
    response = client.post("/inference/localization", files={"image": ("a.png", png(40, 40), "image/png")})
    assert response.status_code == 503
    assert response.json()["detail"] == SERVICE_UNAVAILABLE_DETAIL
    assert RUTA_INTERNA not in response.text and "CUDA" not in response.text


def test_error_inesperado_responde_500_sin_detalles_internos(client, monkeypatch):
    monkeypatch.setattr(inference_router, "inference_service", ServicioQueExplota())
    response = client.post("/inference/localization", files={"image": ("a.png", png(40, 40), "image/png")})
    assert response.status_code == 500
    assert response.json()["detail"] == INTERNAL_ERROR_DETAIL
    assert RUTA_INTERNA not in response.text


# ------------------------------------------------------------------ BUG-10

class ServicioConModelos:
    def list_models(self):
        return [
            {
                "id": "yolo26n-localization",
                "task": "localization",
                "backend": "ultralytics",
                "default": True,
                "enabled": True,
                "available": True,
                "loaded": False,
                "config": {},
            }
        ]


@pytest.mark.parametrize(
    "estado, listo",
    [
        (LifecycleState.AVAILABLE, True),
        (LifecycleState.CLOSED, False),
        (LifecycleState.ERROR, False),
        (LifecycleState.NOT_INITIALIZED, False),
    ],
)
def test_get_models_refleja_el_estado_del_motor(client, monkeypatch, estado, listo):
    monkeypatch.setattr(inference_router, "inference_service", ServicioConModelos())
    monkeypatch.setattr(inference_router, "inference_lifecycle", FakeLifecycle(estado, f"detalle {RUTA_INTERNA}"))
    response = client.get("/models")
    assert response.status_code == 200
    item = response.json()[0]
    assert item["id"] == "yolo26n-localization"  # los campos de siempre siguen ahí
    assert item["engine_state"] == estado.value
    assert item["engine_ready"] is listo
    assert RUTA_INTERNA not in response.text


def test_get_models_cambia_al_apagar_el_motor(client, monkeypatch):
    # El escenario del reporte: GET /models, apagar, GET /models.
    monkeypatch.setattr(inference_router, "inference_service", ServicioConModelos())
    monkeypatch.setattr(inference_router, "inference_lifecycle", FakeLifecycle(LifecycleState.AVAILABLE))
    antes = client.get("/models").json()
    monkeypatch.setattr(inference_router, "inference_lifecycle", FakeLifecycle(LifecycleState.CLOSED))
    despues = client.get("/models").json()
    assert antes != despues
    assert (antes[0]["engine_state"], despues[0]["engine_state"]) == ("available", "closed")
