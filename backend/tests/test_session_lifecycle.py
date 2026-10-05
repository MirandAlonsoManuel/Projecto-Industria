"""
Pruebas del ciclo de vida de la sesión — M07 (OMC-88), nivel gestor.

Todas corren sin cámara física: `open_camera` se reemplaza por una cámara
simulada que cuenta aperturas, cierres e instancias abiertas a la vez, y que
detecta si alguien intenta cerrarla mientras se está leyendo un frame.

Criterios cubiertos:
  C1  Todas las operaciones están disponibles mediante una interfaz coherente.
  C2  Las transiciones inválidas generan errores controlados.
  C3  Solo se admite una sesión y un cliente activo.
  C4  El apagado global es idempotente y comprobable.

Ejecutar:
    cd backend
    python -m pytest tests/test_session_lifecycle.py -v
"""

from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest

from app.services import camera_session_manager as manager_module
from app.services.camera_session_manager import (
    CameraMismatchError,
    CameraSessionManager,
    ClientSessionEndedError,
    NoClientConnectedError,
    ServiceShuttingDownError,
    SessionAlreadyActiveError,
    SessionBusyError,
    SessionError,
    SessionNotActiveError,
    SessionStatus,
    StartedBy,
)


# ── Cámara simulada ───────────────────────────────────────────────────────────

class CameraStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.opens = 0
        self.releases = 0
        self.active = 0
        self.max_active = 0
        self.released_while_reading = False

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
    is_opened = True

    def __init__(self, stats: CameraStats, read_delay: float) -> None:
        self._stats = stats
        self._read_delay = read_delay
        self._reading = False
        self._released = False
        stats.opened()

    def read_frame(self):
        self._reading = True
        time.sleep(self._read_delay)
        self._reading = False
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self) -> None:
        if self._reading:
            self._stats.released_while_reading = True
        if not self._released:
            self._released = True
            self._stats.closed()


@pytest.fixture
def stats() -> CameraStats:
    return CameraStats()


@pytest.fixture
def camera(monkeypatch, stats):
    config = {"open_delay": 0.01, "read_delay": 0.0}

    def fake_open_camera(source: str):
        time.sleep(config["open_delay"])
        return FakeCapture(stats, config["read_delay"])

    monkeypatch.setattr(manager_module, "open_camera", fake_open_camera)
    return config


@pytest.fixture
def manager() -> CameraSessionManager:
    return CameraSessionManager()


def run(coro):
    return asyncio.run(coro)


def eventos(manager: CameraSessionManager) -> list[str]:
    return [e["event"] for e in manager.get_status()["events"]]


# ── C1: operaciones disponibles y transiciones válidas ───────────────────────

def test_c1_start_deja_la_sesion_en_running_sin_cliente(manager, camera, stats):
    session = run(manager.start("0"))

    assert manager.state == SessionStatus.RUNNING
    assert session.started_by == StartedBy.OPERATOR
    assert session.active_client is None
    assert stats.active == 1
    assert eventos(manager) == ["started"]


def test_c1_stop_cierra_la_camara_y_vuelve_a_idle(manager, camera, stats):
    async def escenario():
        await manager.start("0")
        await manager.stop()

    run(escenario())

    assert manager.state == SessionStatus.IDLE
    assert stats.active == 0
    assert eventos(manager) == ["started", "stopped"]


def test_c1_cliente_sin_sesion_la_inicia_y_al_irse_la_cierra(manager, camera, stats):
    async def escenario():
        session = await manager.connect_client("0", "cliente-1")
        assert manager.state == SessionStatus.STREAMING
        assert session.started_by == StartedBy.CLIENT
        await manager.disconnect_client("cliente-1")

    run(escenario())

    assert manager.state == SessionStatus.IDLE
    assert stats.active == 0
    assert eventos(manager) == [
        "started", "client_connected", "client_disconnected", "stopped",
    ]


def test_c1_sesion_de_operador_sigue_abierta_al_irse_el_cliente(manager, camera, stats):
    async def escenario():
        await manager.start("0")
        await manager.connect_client("0", "cliente-1")
        await manager.disconnect_client("cliente-1")
        assert manager.state == SessionStatus.RUNNING
        # El siguiente cliente entra sin reabrir el hardware
        await manager.connect_client("0", "cliente-2")

    run(escenario())

    assert manager.state == SessionStatus.STREAMING
    assert stats.opens == 1


def test_c1_read_frame_entrega_frames_al_cliente_activo(manager, camera):
    async def escenario():
        await manager.connect_client("0", "cliente-1")
        return await manager.read_frame("cliente-1")

    frame = run(escenario())

    assert frame is not None
    assert manager.session.metrics.frames_total == 1


def test_c1_estado_expone_ciclo_de_vida_completo(manager, camera):
    run(manager.connect_client("0", "cliente-1"))

    status = manager.get_status()

    assert status["state"] == "streaming"
    assert status["started_by"] == "client"
    assert status["accepting_clients"] is True
    assert status["events"][-1]["event"] == "client_connected"
    assert status["events"][-1]["client_id"] == "cliente-1"


# ── C2: transiciones inválidas con errores controlados ───────────────────────

def test_c2_start_dos_veces(manager, camera, stats):
    async def escenario():
        await manager.start("0")
        await manager.start("0")

    with pytest.raises(SessionAlreadyActiveError) as info:
        run(escenario())

    assert info.value.code == "SESSION_ALREADY_ACTIVE"
    assert stats.opens == 1


def test_c2_stop_sin_sesion(manager):
    with pytest.raises(SessionNotActiveError) as info:
        run(manager.stop())
    assert info.value.code == "SESSION_NOT_ACTIVE"


def test_c2_desconectar_sin_cliente(manager, camera):
    async def escenario():
        await manager.start("0")
        await manager.force_disconnect()

    with pytest.raises(NoClientConnectedError) as info:
        run(escenario())
    assert info.value.code == "NO_CLIENT_CONNECTED"


def test_c2_cliente_pide_otra_camara(manager, camera):
    async def escenario():
        await manager.start("0")
        await manager.connect_client("1", "cliente-1")

    with pytest.raises(CameraMismatchError) as info:
        run(escenario())

    assert info.value.code == "CAMERA_MISMATCH"
    assert manager.state == SessionStatus.RUNNING


def test_c2_todos_los_errores_tienen_codigo_y_estado_http():
    for error in (
        SessionBusyError, SessionAlreadyActiveError, SessionNotActiveError,
        NoClientConnectedError, CameraMismatchError, ServiceShuttingDownError,
    ):
        assert issubclass(error, SessionError)
        assert error.code != SessionError.code
        assert error.http_status in (409, 503)


def test_c2_stop_con_cliente_le_avisa_session_stopped(manager, camera, stats):
    async def escenario():
        await manager.connect_client("0", "cliente-1")
        await manager.stop()
        await manager.read_frame("cliente-1")

    with pytest.raises(ClientSessionEndedError) as info:
        run(escenario())

    assert info.value.code == "SESSION_STOPPED"
    assert stats.active == 0


def test_c2_desconexion_forzada_le_avisa_client_disconnected(manager, camera, stats):
    async def escenario():
        await manager.start("0")
        await manager.connect_client("0", "cliente-1")
        expulsado = await manager.force_disconnect()
        assert expulsado == "cliente-1"
        await manager.read_frame("cliente-1")

    with pytest.raises(ClientSessionEndedError) as info:
        run(escenario())

    assert info.value.code == "CLIENT_DISCONNECTED"
    # La sesión la inició un operador: la cámara sigue abierta
    assert manager.state == SessionStatus.RUNNING
    assert stats.active == 1


# ── C3: una sola sesión y un solo cliente, también bajo concurrencia ─────────

def test_c3_segundo_cliente_rechazado_sin_alterar_al_activo(manager, camera):
    async def escenario():
        await manager.connect_client("0", "cliente-1")
        with pytest.raises(SessionBusyError):
            await manager.connect_client("0", "cliente-2")
        return await manager.read_frame("cliente-1")

    assert run(escenario()) is not None
    assert manager.session.active_client == "cliente-1"


def test_c3_inicios_simultaneos_una_sola_apertura(manager, camera, stats):
    async def escenario():
        return await asyncio.gather(
            *(manager.start("0") for _ in range(10)), return_exceptions=True
        )

    resultados = run(escenario())

    errores = [r for r in resultados if isinstance(r, SessionAlreadyActiveError)]
    assert len(errores) == 9
    assert stats.opens == 1


def test_c3_detenciones_simultaneas_un_solo_cierre(manager, camera, stats):
    async def escenario():
        await manager.start("0")
        return await asyncio.gather(
            *(manager.stop() for _ in range(5)), return_exceptions=True
        )

    resultados = run(escenario())

    errores = [r for r in resultados if isinstance(r, SessionNotActiveError)]
    assert len(errores) == 4
    assert stats.releases == 1


def test_c3_stop_espera_la_lectura_en_curso(manager, camera, stats):
    camera["read_delay"] = 0.1

    async def escenario():
        await manager.connect_client("0", "cliente-1")
        lectura = asyncio.create_task(manager.read_frame("cliente-1"))
        await asyncio.sleep(0.02)  # la lectura ya está en el hilo
        await manager.stop()
        return await lectura

    frame = run(escenario())

    assert frame is not None
    assert stats.released_while_reading is False
    assert stats.active == 0


def test_c3_operaciones_mezcladas_dejan_estado_determinista(manager, camera, stats):
    """Muchos clientes, inicios y detenciones a la vez: nunca dos cámaras abiertas."""
    camera["open_delay"] = 0.002

    async def cliente(nombre: str) -> None:
        for _ in range(5):
            try:
                await manager.connect_client("0", nombre)
                await manager.read_frame(nombre)
            except (SessionError, ClientSessionEndedError):
                pass
            await manager.disconnect_client(nombre)

    async def operador() -> None:
        for _ in range(5):
            for operacion in (manager.start("0"), manager.stop()):
                try:
                    await operacion
                except SessionError:
                    pass
            await asyncio.sleep(0.001)

    async def escenario():
        await asyncio.gather(*(cliente(f"c{i}") for i in range(6)), operador())
        if manager.session is not None:
            await manager.stop()

    run(escenario())

    assert stats.max_active == 1
    assert stats.opens == stats.releases
    assert manager.state == SessionStatus.IDLE


# ── C4: apagado global idempotente y comprobable ─────────────────────────────

def test_c4_shutdown_libera_y_es_idempotente(manager, camera, stats):
    async def escenario():
        await manager.connect_client("0", "cliente-1")
        primero = await manager.shutdown()
        segundo = await manager.shutdown()
        return primero, segundo

    primero, segundo = run(escenario())

    assert (primero, segundo) == (True, False)
    assert stats.active == 0
    status = manager.get_status()
    assert status["state"] == "idle"
    assert status["accepting_clients"] is False
    shutdowns = [e for e in status["events"] if e["event"] == "shutdown"]
    assert [e["reason"] for e in shutdowns] == ["released", "already_idle"]


def test_c4_shutdown_avisa_al_cliente_conectado(manager, camera):
    async def escenario():
        await manager.connect_client("0", "cliente-1")
        await manager.shutdown()
        await manager.read_frame("cliente-1")

    with pytest.raises(ClientSessionEndedError) as info:
        run(escenario())
    assert info.value.code == "SERVICE_SHUTDOWN"


def test_c4_tras_shutdown_no_se_aceptan_sesiones_nuevas(manager, camera, stats):
    async def escenario():
        await manager.shutdown()
        for operacion in (manager.start("0"), manager.connect_client("0", "tarde")):
            with pytest.raises(ServiceShuttingDownError):
                await operacion

    run(escenario())

    assert stats.opens == 0


def test_c4_shutdown_compite_con_conexiones_sin_dejar_camara_abierta(manager, camera, stats):
    async def escenario():
        resultados = await asyncio.gather(
            *(manager.connect_client("0", f"c{i}") for i in range(5)),
            manager.shutdown(),
            *(manager.connect_client("0", f"d{i}") for i in range(5)),
            return_exceptions=True,
        )
        return resultados

    run(escenario())

    assert stats.active == 0
    assert manager.state == SessionStatus.IDLE
    assert manager.is_accepting is False
