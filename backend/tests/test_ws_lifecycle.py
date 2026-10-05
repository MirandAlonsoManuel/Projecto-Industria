"""
Pruebas del ciclo de vida por WebSocket — M07 (OMC-88).

Verifican que `/ws/stream` y `/ws/inference-stream` comparten la misma sesión
y responden con los mismos mensajes y códigos de cierre en cada transición.
Las acciones de operador (start, stop, desconexión, apagado) se invocan sobre
el gestor dentro del mismo event loop del servidor de pruebas.

Sin cámara física ni modelos: `open_camera`, la inferencia y el ROI se simulan.

Ejecutar:
    cd backend
    python -m pytest tests/test_ws_lifecycle.py -v
"""

from __future__ import annotations

import json
import threading
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import inference as inference_router
from app.api.routers import stream as stream_router
from app.services import camera_session_manager as manager_module
from app.services.camera_session_manager import CameraSessionManager


# ── Cámara y modelo simulados ────────────────────────────────────────────────

class CameraStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.opens = 0
        self.active = 0

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


class FakeInference:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def localize(self, frame, model_id, conf, iou, offset):
        self.calls += 1
        if self.fail:
            raise RuntimeError("modelo no disponible")
        return "fake-model", [{"label": "pieza", "confidence": 0.9}]


@pytest.fixture
def stats(monkeypatch) -> CameraStats:
    camera_stats = CameraStats()
    monkeypatch.setattr(
        manager_module, "open_camera", lambda source: FakeCapture(camera_stats)
    )
    return camera_stats


@pytest.fixture
def fake_inference(monkeypatch) -> FakeInference:
    fake = FakeInference()
    monkeypatch.setattr(inference_router, "inference_service", fake)
    monkeypatch.setattr(
        inference_router, "_roi_query", lambda frame, *args: (frame, None, (0, 0))
    )
    return fake


@pytest.fixture
def gestor(monkeypatch, stats) -> CameraSessionManager:
    nuevo = CameraSessionManager()
    monkeypatch.setattr(stream_router, "camera_session_manager", nuevo)
    monkeypatch.setattr(inference_router, "camera_session_manager", nuevo)
    return nuevo


@pytest.fixture
def client(gestor, fake_inference):
    app = FastAPI()
    app.include_router(stream_router.router)
    app.include_router(inference_router.router)
    with TestClient(app) as test_client:
        yield test_client


def operador(client: TestClient, accion, *args):
    """Ejecuta una operación del gestor en el event loop del servidor."""
    return client.portal.call(accion, *args)


def esperar(condicion, limite: float = 2.0) -> None:
    """El cierre del hardware ocurre en el servidor; se espera a que termine."""
    fin = time.monotonic() + limite
    while not condicion():
        assert time.monotonic() < fin, "la condición no se cumplió a tiempo"
        time.sleep(0.01)


def esperar_fin(ws) -> tuple[dict, int]:
    """Descarta frames hasta el mensaje JSON de fin y devuelve (mensaje, código de cierre)."""
    while True:
        mensaje = ws.receive()
        if mensaje.get("text"):
            datos = json.loads(mensaje["text"])
            cierre = ws.receive()
            assert cierre["type"] == "websocket.close"
            return datos, cierre["code"]


# ── Conexión y bienvenida ────────────────────────────────────────────────────

def test_bienvenida_informa_estado_y_origen_de_la_sesion(client):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        bienvenida = ws.receive_json()
        ws.receive_bytes()

    assert bienvenida["connected"] is True
    assert bienvenida["state"] == "streaming"
    assert bienvenida["started_by"] == "client"
    assert bienvenida["error"] is None
    assert bienvenida["client_id"]


def test_cliente_de_sesion_automatica_la_cierra_al_salir(client, gestor, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()

    esperar(lambda: gestor.state.value == "idle")
    assert stats.active == 0
    eventos = [e["event"] for e in gestor.get_status()["events"]]
    assert eventos == ["started", "client_connected", "client_disconnected", "stopped"]


def test_sesion_de_operador_queda_abierta_al_salir_el_cliente(client, gestor, stats):
    operador(client, gestor.start, "0")

    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        assert ws.receive_json()["started_by"] == "operator"
        ws.receive_bytes()

    assert gestor.state.value == "running"
    assert stats.active == 1


# ── Fin de la sesión por acciones externas ───────────────────────────────────

def test_stop_avisa_session_stopped_y_cierra_con_1000(client, gestor, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()
        operador(client, gestor.stop)
        fin, codigo = esperar_fin(ws)

    assert fin["error"] == "SESSION_STOPPED"
    assert codigo == 1000
    assert stats.active == 0


def test_desconexion_forzada_avisa_client_disconnected(client, gestor):
    operador(client, gestor.start, "0")

    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()
        operador(client, gestor.force_disconnect)
        fin, codigo = esperar_fin(ws)

    assert fin["error"] == "CLIENT_DISCONNECTED"
    assert codigo == 1000
    assert gestor.state.value == "running"


def test_shutdown_avisa_al_cliente_y_rechaza_nuevas_conexiones(client, gestor, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()
        operador(client, gestor.shutdown)
        fin, codigo = esperar_fin(ws)

    assert fin["error"] == "SERVICE_SHUTDOWN"
    assert codigo == 1001

    with client.websocket_connect("/ws/stream?camera_id=0") as tarde:
        rechazo, codigo = esperar_fin(tarde)

    assert rechazo["error"] == "SERVICE_SHUTTING_DOWN"
    assert codigo == 1001
    assert stats.active == 0


# ── Transiciones inválidas al conectar ───────────────────────────────────────

def test_camara_distinta_a_la_de_la_sesion_se_rechaza(client, gestor):
    operador(client, gestor.start, "0")

    with client.websocket_connect("/ws/stream?camera_id=1") as ws:
        rechazo, codigo = esperar_fin(ws)

    assert rechazo["error"] == "CAMERA_MISMATCH"
    assert codigo == 1008
    assert gestor.state.value == "running"


# ── Coherencia entre /ws/stream y /ws/inference-stream ───────────────────────

def test_inference_stream_entrega_detecciones(client, fake_inference):
    with client.websocket_connect("/ws/inference-stream?camera_id=0&infer_every_n_frames=1") as ws:
        bienvenida = ws.receive_json()
        frame = ws.receive_bytes()

    longitud = int.from_bytes(frame[:4], "big")
    metadatos = json.loads(frame[4:4 + longitud])
    assert bienvenida["state"] == "streaming"
    assert metadatos["detections"] == [{"label": "pieza", "confidence": 0.9}]
    assert fake_inference.calls >= 1


def test_ambos_websocket_comparten_un_solo_cliente(client, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as stream:
        stream.receive_json()
        stream.receive_bytes()

        with client.websocket_connect("/ws/inference-stream?camera_id=0") as inferencia:
            rechazo, codigo = esperar_fin(inferencia)

        assert rechazo["error"] == "CAMERA_BUSY"
        assert codigo == 1008
        assert len(stream.receive_bytes()) > 0

    assert stats.opens == 1


def test_inference_stream_responde_igual_ante_stop(client, gestor):
    with client.websocket_connect("/ws/inference-stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()
        operador(client, gestor.stop)
        fin, codigo = esperar_fin(ws)

    assert fin["error"] == "SESSION_STOPPED"
    assert codigo == 1000


def test_falla_de_inferencia_cierra_con_processing_error(client, gestor, fake_inference, stats):
    fake_inference.fail = True

    with client.websocket_connect("/ws/inference-stream?camera_id=0") as ws:
        ws.receive_json()
        fin, codigo = esperar_fin(ws)

    assert fin["error"] == "PROCESSING_ERROR"
    assert codigo == 1011
    esperar(lambda: stats.active == 0)


# ── Orden inequívoco de eventos ──────────────────────────────────────────────

def test_eventos_tienen_seq_consecutivo(client, gestor):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()

    esperar(lambda: gestor.state.value == "idle")
    secuencia = [e["seq"] for e in gestor.get_status()["events"]]
    assert secuencia == list(range(1, len(secuencia) + 1))
