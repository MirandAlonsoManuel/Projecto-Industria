
from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.routers import cameras as cameras_router
from app.api.routers import stream as stream_router
from app.services import camera_session_manager as manager_module
from app.services.camera_session_manager import (
    CameraSession,
    CameraSessionManager,
    SessionBusyError,
    SessionCameraError,
)


# ── Cámara simulada ───────────────────────────────────────────────────────────

class CameraStats:
    """Contabilidad compartida de aperturas, cierres e instancias simultáneas."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.opens = 0
        self.releases = 0
        self.active = 0
        self.max_active = 0

    def opened(self) -> None:
        with self._lock:
            self.opens += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def closed(self) -> None:
        with self._lock:
            self.releases += 1
            self.active -= 1


class FakeCapture:
    def __init__(self, stats: CameraStats, fail_on_release: bool = False) -> None:
        self._stats = stats
        self._fail_on_release = fail_on_release
        self._released = False
        stats.opened()

    is_opened = True

    def read_frame(self):
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._stats.closed()
        if self._fail_on_release:
            raise RuntimeError("fallo simulado del driver al cerrar")


@pytest.fixture
def stats() -> CameraStats:
    return CameraStats()


@pytest.fixture
def fake_camera(monkeypatch, stats):
    config = {"delay": 0.02, "fail_on_release": False, "raise_on_open": None}

    def fake_open_camera(source: str):
        time.sleep(config["delay"])
        if config["raise_on_open"] is not None:
            raise config["raise_on_open"]
        return FakeCapture(stats, fail_on_release=config["fail_on_release"])

    monkeypatch.setattr(manager_module, "open_camera", fake_open_camera)
    return config


@pytest.fixture
def manager() -> CameraSessionManager:
    return CameraSessionManager()


def run(coro):
    return asyncio.run(coro)


# ── C1: una instancia de captura y una sesión ────────────────────────────────

def test_c1_una_sola_sesion_y_una_sola_captura(manager, fake_camera, stats):
    session = run(manager.acquire("0", "cliente-1"))

    assert manager.session is session
    assert manager.is_busy
    assert stats.opens == 1
    assert stats.active == 1


# ── C2: segundo cliente con error controlado, sin afectar al activo ───────────

def test_c2_segundo_cliente_recibe_error_controlado(manager, fake_camera, stats):
    async def escenario():
        activo = await manager.acquire("0", "cliente-1")
        with pytest.raises(SessionBusyError) as info:
            await manager.acquire("0", "cliente-2")
        return activo, info.value

    activo, error = run(escenario())

    assert error.code == "CAMERA_BUSY"
    # El cliente activo conserva su sesión y su captura sigue entregando frames
    assert manager.session is activo
    assert activo.active_client == "cliente-1"
    assert activo.capture.read_frame() is not None
    assert stats.opens == 1
    assert stats.releases == 0


def test_c2_liberacion_tardia_no_cierra_sesion_nueva(manager, fake_camera, stats):
    """Una conexión vieja que libera tarde no puede cerrar la sesión de otra."""
    async def escenario():
        await manager.acquire("0", "cliente-viejo")
        await manager.release("cliente-viejo")
        await manager.acquire("0", "cliente-nuevo")
        return await manager.release("cliente-viejo")

    liberado = run(escenario())

    assert liberado is False
    assert manager.session.active_client == "cliente-nuevo"
    assert stats.active == 1


# ── C3: al desconectarse, todo queda disponible ──────────────────────────────

def test_c3_release_deja_recurso_disponible(manager, fake_camera, stats):
    async def escenario():
        await manager.acquire("0", "cliente-1")
        assert await manager.release("cliente-1") is True
        await manager.acquire("0", "cliente-2")

    run(escenario())

    assert manager.session.active_client == "cliente-2"
    assert stats.opens == 2
    assert stats.releases == 1
    assert stats.max_active == 1


def test_c3_release_concurrente_es_idempotente(manager, fake_camera, stats):
    async def escenario():
        await manager.acquire("0", "cliente-1")
        return await asyncio.gather(*(manager.release("cliente-1") for _ in range(5)))

    resultados = run(escenario())

    assert resultados.count(True) == 1
    assert stats.releases == 1
    assert manager.session is None


def test_c3_error_del_driver_al_cerrar_no_secuestra_la_camara(manager, fake_camera, stats):
    fake_camera["fail_on_release"] = True

    async def escenario():
        await manager.acquire("0", "cliente-1")
        await manager.release("cliente-1")
        fake_camera["fail_on_release"] = False
        await manager.acquire("0", "cliente-2")

    run(escenario())

    assert manager.session.active_client == "cliente-2"


def test_c3_excepcion_del_driver_al_abrir_no_deja_sesion(manager, fake_camera):
    fake_camera["raise_on_open"] = OSError("dispositivo ocupado por el sistema")

    with pytest.raises(SessionCameraError) as info:
        run(manager.acquire("0", "cliente-1"))

    assert info.value.code == "CAMERA_UNAVAILABLE"
    assert manager.session is None

    fake_camera["raise_on_open"] = None
    run(manager.acquire("0", "cliente-2"))
    assert manager.session.active_client == "cliente-2"


def test_c3_cancelacion_durante_apertura_cierra_la_captura_huerfana(
    manager, fake_camera, stats
):
    fake_camera["delay"] = 0.2

    async def escenario():
        tarea = asyncio.create_task(manager.acquire("0", "cliente-cancelado"))
        await asyncio.sleep(0.05)  # la apertura está en curso en otro hilo
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea
        await asyncio.sleep(0)
        assert manager.session is None
        assert stats.active == 0  # la captura que llegó tarde se cerró

        fake_camera["delay"] = 0.0
        await manager.acquire("0", "cliente-2")

    run(escenario())

    assert manager.session.active_client == "cliente-2"
    assert stats.max_active == 1


def test_c3_shutdown_libera_la_sesion_activa(manager, fake_camera, stats):
    async def escenario():
        await manager.acquire("0", "cliente-1")
        await manager.shutdown()

    run(escenario())

    assert manager.session is None
    assert stats.active == 0


# ── C4: concurrencia sin aperturas duplicadas ────────────────────────────────

def test_c4_veinte_clientes_simultaneos_una_sola_apertura(manager, fake_camera, stats):
    async def escenario():
        return await asyncio.gather(
            *(manager.acquire("0", f"cliente-{i}") for i in range(20)),
            return_exceptions=True,
        )

    resultados = run(escenario())

    exitos = [r for r in resultados if isinstance(r, CameraSession)]
    ocupados = [r for r in resultados if isinstance(r, SessionBusyError)]
    assert len(exitos) == 1
    assert len(ocupados) == 19
    assert stats.opens == 1
    assert stats.max_active == 1


def test_c4_ciclos_de_adquirir_y_liberar_nunca_duplican(manager, fake_camera, stats):
    fake_camera["delay"] = 0.005

    async def cliente(nombre: str) -> int:
        usos = 0
        for _ in range(10):
            try:
                await manager.acquire("0", nombre)
            except SessionBusyError:
                await asyncio.sleep(0.001)
                continue
            usos += 1
            await asyncio.sleep(0.002)
            await manager.release(nombre)
        return usos

    async def escenario():
        return await asyncio.gather(*(cliente(f"cliente-{i}") for i in range(8)))

    usos = run(escenario())

    assert sum(usos) >= 1
    assert stats.max_active == 1
    assert stats.opens == stats.releases == sum(usos)


def test_c4_escaneo_no_abre_la_camara_en_uso(manager, fake_camera):
    exclusiones = []

    def detector(max_index: int = 4, exclude=None):
        exclusiones.append(set(exclude or ()))
        return [
            {"id": "1", "type": "usb", "source_url": "1", "status": "available"}
        ]

    async def escenario():
        await manager.acquire("0", "cliente-1")
        return await manager.scan_cameras(detector)

    camaras = run(escenario())

    assert exclusiones == [{"0"}]
    assert camaras[0] == {
        "id": "0", "type": "usb", "source_url": "0", "status": "in_use"
    }
    assert camaras[1]["status"] == "available"


# ── Integración por WebSocket y REST ─────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, fake_camera):
    """App mínima con los routers reales y un gestor nuevo por prueba."""
    gestor = CameraSessionManager()
    monkeypatch.setattr(stream_router, "camera_session_manager", gestor)
    monkeypatch.setattr(cameras_router, "camera_session_manager", gestor)

    app = FastAPI()
    app.include_router(stream_router.router)
    app.include_router(cameras_router.router)
    with TestClient(app) as test_client:
        yield test_client


def test_ws_segundo_cliente_rechazado_y_primero_sigue_transmitiendo(client, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as primero:
        assert primero.receive_json()["connected"] is True
        primero.receive_bytes()

        with client.websocket_connect("/ws/stream?camera_id=0") as segundo:
            rechazo = segundo.receive_json()
            assert rechazo["connected"] is False
            assert rechazo["error"] == "CAMERA_BUSY"
            with pytest.raises(WebSocketDisconnect) as cierre:
                segundo.receive_json()
            assert cierre.value.code == 1008

        # El primer cliente no se enteró del intento: sigue recibiendo video
        assert len(primero.receive_bytes()) > 0

    assert stats.opens == 1


def test_ws_desconexion_libera_para_un_nuevo_cliente(client, stats):
    with client.websocket_connect("/ws/stream?camera_id=0") as primero:
        assert primero.receive_json()["connected"] is True
        primero.receive_bytes()

    # Al salir del bloque el primer cliente se desconecta
    estado = client.get("/cameras/session").json()
    assert estado["status"] == "idle"

    with client.websocket_connect("/ws/stream?camera_id=0") as segundo:
        assert segundo.receive_json()["connected"] is True

    assert stats.opens == 2
    assert stats.max_active == 1


def test_rest_estado_de_sesion_mientras_transmite(client):
    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        ws.receive_bytes()
        estado = client.get("/cameras/session").json()
        assert estado["status"] == "streaming"
        assert estado["camera_id"] == "0"
