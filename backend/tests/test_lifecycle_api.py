"""
Pruebas de la interfaz REST del ciclo de vida y del apagado global — M07 (OMC-88).

Cubren los endpoints de operador (`start`, `stop`, `disconnect`), sus errores
controlados y el apagado global conectado al cierre de la aplicación FastAPI.
Sin cámara física: `open_camera` se reemplaza por una cámara simulada.

Ejecutar:
    cd backend
    python -m pytest tests/test_lifecycle_api.py -v
"""

from __future__ import annotations

import json
import threading
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import main as main_module
from app.api.routers import cameras as cameras_router
from app.api.routers import inference as inference_router
from app.api.routers import stream as stream_router
from app.services import camera_session_manager as manager_module
from app.services.camera_session_manager import CameraSessionManager


# ── Cámara simulada ───────────────────────────────────────────────────────────

class CameraStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.opens = 0
        self.active = 0
        self.fail_open = False

    def opened(self) -> None:
        with self._lock:
            self.opens += 1
            self.active += 1

    def closed(self) -> None:
        with self._lock:
            self.active -= 1


class FakeCapture:
    is_opened = True

    def __init__(self, stats: CameraStats) -> None:
        self._stats = stats
        self._released = False
        stats.opened()

    def read_frame(self):
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._stats.closed()


@pytest.fixture
def stats(monkeypatch) -> CameraStats:
    camera_stats = CameraStats()

    def fake_open_camera(source: str):
        if camera_stats.fail_open:
            return None
        return FakeCapture(camera_stats)

    monkeypatch.setattr(manager_module, "open_camera", fake_open_camera)
    return camera_stats


@pytest.fixture
def gestor(monkeypatch, stats) -> CameraSessionManager:
    nuevo = CameraSessionManager()
    for modulo in (main_module, cameras_router, stream_router, inference_router):
        monkeypatch.setattr(modulo, "camera_session_manager", nuevo)
    return nuevo


@pytest.fixture
def client(gestor):
    app = FastAPI()
    app.include_router(cameras_router.router)
    app.include_router(stream_router.router)
    with TestClient(app) as test_client:
        yield test_client


def esperar(condicion, limite: float = 2.0) -> None:
    fin = time.monotonic() + limite
    while not condicion():
        assert time.monotonic() < fin, "la condición no se cumplió a tiempo"
        time.sleep(0.01)


def esperar_fin(ws) -> tuple[dict, int]:
    while True:
        mensaje = ws.receive()
        if mensaje.get("text"):
            datos = json.loads(mensaje["text"])
            cierre = ws.receive()
            return datos, cierre["code"]


# ── C1: operaciones disponibles por una interfaz coherente ───────────────────

def test_start_inicia_la_sesion_en_running(client, stats):
    respuesta = client.post("/cameras/session/start", params={"camera_id": "0"})

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["error"] is None
    assert cuerpo["data"]["state"] == "running"
    assert cuerpo["data"]["started_by"] == "operator"
    assert stats.active == 1


def test_stop_detiene_la_sesion(client, stats):
    client.post("/cameras/session/start")
    respuesta = client.post("/cameras/session/stop")

    assert respuesta.status_code == 200
    assert respuesta.json()["data"]["state"] == "idle"
    assert stats.active == 0


def test_ciclo_completo_por_rest_y_websocket(client, gestor, stats):
    client.post("/cameras/session/start")

    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        assert ws.receive_json()["started_by"] == "operator"
        ws.receive_bytes()
        assert client.get("/cameras/session").json()["state"] == "streaming"

    esperar(lambda: client.get("/cameras/session").json()["state"] == "running")
    client.post("/cameras/session/stop")

    estado = client.get("/cameras/session").json()
    assert estado["state"] == "idle"
    assert [e["event"] for e in estado["events"]] == [
        "started", "client_connected", "client_disconnected", "stopped",
    ]
    assert stats.opens == 1


def test_disconnect_expulsa_al_cliente_y_conserva_la_camara(client, stats):
    client.post("/cameras/session/start")

    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()
        respuesta = client.post("/cameras/session/disconnect")
        fin, codigo = esperar_fin(ws)

    assert respuesta.status_code == 200
    assert respuesta.json()["data"]["client_id"]
    assert respuesta.json()["data"]["state"] == "running"
    assert fin["error"] == "CLIENT_DISCONNECTED"
    assert codigo == 1000
    assert stats.active == 1


def test_stop_con_cliente_conectado_le_avisa(client, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()
        respuesta = client.post("/cameras/session/stop")
        fin, codigo = esperar_fin(ws)

    assert respuesta.status_code == 200
    assert fin["error"] == "SESSION_STOPPED"
    assert codigo == 1000
    assert stats.active == 0


# ── C2: transiciones inválidas con errores controlados ───────────────────────

@pytest.mark.parametrize(
    "preparacion, endpoint, codigo_http, error",
    [
        (["/cameras/session/start"], "/cameras/session/start", 409, "SESSION_ALREADY_ACTIVE"),
        ([], "/cameras/session/stop", 409, "SESSION_NOT_ACTIVE"),
        ([], "/cameras/session/disconnect", 409, "NO_CLIENT_CONNECTED"),
        (["/cameras/session/start"], "/cameras/session/disconnect", 409, "NO_CLIENT_CONNECTED"),
    ],
)
def test_transiciones_invalidas(client, preparacion, endpoint, codigo_http, error):
    for paso in preparacion:
        client.post(paso)

    respuesta = client.post(endpoint)

    assert respuesta.status_code == codigo_http
    cuerpo = respuesta.json()
    assert cuerpo["error"] == error
    assert cuerpo["meta"]["description"]
    assert "state" in cuerpo["data"]  # el estado actual acompaña al error


def test_camara_no_disponible_responde_503(client, stats):
    stats.fail_open = True

    respuesta = client.post("/cameras/session/start")

    assert respuesta.status_code == 503
    assert respuesta.json()["error"] == "CAMERA_UNAVAILABLE"
    assert respuesta.json()["data"]["state"] == "idle"


def test_error_no_altera_la_sesion_activa(client, stats):
    client.post("/cameras/session/start")
    antes = client.get("/cameras/session").json()

    client.post("/cameras/session/start")
    despues = client.get("/cameras/session").json()

    assert despues["state"] == antes["state"] == "running"
    assert despues["events"] == antes["events"]
    assert stats.opens == 1


# ── C3: una sesión y un cliente ──────────────────────────────────────────────

def test_segundo_cliente_rechazado_con_sesion_de_operador(client, stats):
    client.post("/cameras/session/start")

    with client.websocket_connect("/ws/stream?camera_id=0") as primero:
        primero.receive_json()
        primero.receive_bytes()
        with client.websocket_connect("/ws/stream?camera_id=0") as segundo:
            rechazo, codigo = esperar_fin(segundo)
        assert len(primero.receive_bytes()) > 0

    assert rechazo["error"] == "CAMERA_BUSY"
    assert codigo == 1008
    assert stats.opens == 1


# ── C4: apagado global idempotente y comprobable ─────────────────────────────

def test_apagado_global_al_cerrar_la_aplicacion(gestor, stats):
    app = main_module.create_app()

    with TestClient(app) as client:
        client.post("/cameras/session/start")
        assert stats.active == 1

    # Al salir del bloque, FastAPI ejecuta el lifespan de apagado
    assert stats.active == 0
    estado = gestor.get_lifecycle_status()
    assert estado["state"] == "idle"
    assert estado["accepting_clients"] is False
    assert estado["events"][-1]["event"] == "shutdown"
    assert estado["events"][-1]["reason"] == "released"


def test_apagado_global_sin_sesion_y_repetido(gestor, stats):
    app = main_module.create_app()

    with TestClient(app):
        pass
    with TestClient(app):
        pass

    shutdowns = [e for e in gestor.get_lifecycle_status()["events"] if e["event"] == "shutdown"]
    assert [e["reason"] for e in shutdowns] == ["already_idle", "already_idle"]
    assert stats.opens == 0


def test_tras_apagado_se_rechazan_operaciones(client, gestor):
    client.portal.call(gestor.shutdown)

    respuesta = client.post("/cameras/session/start")

    assert respuesta.status_code == 503
    assert respuesta.json()["error"] == "SERVICE_SHUTTING_DOWN"
