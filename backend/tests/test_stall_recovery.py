"""
Pruebas de detección de cámara estancada y recuperación — M10 (OMC-91).

Sin cámara física: cada apertura entrega una cámara simulada con un
comportamiento elegido por la prueba. Los tiempos se reducen inyectando
parámetros al gestor, para que cada prueba tarde décimas de segundo.

Criterios cubiertos:
  C1  El sistema distingue una cámara activa de una cámara estancada.
  C2  La falta de frames después del umbral dispara recuperación controlada.
  C3  La última actividad y el motivo de recuperación quedan registrados.
  C4  La recuperación conserva el límite de una sesión y un cliente.

Ejecutar:
    cd backend
    python -m pytest tests/test_stall_recovery.py -v
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import cameras as cameras_router
from app.api.routers import stream as stream_router
from app.services import camera_session_manager as manager_module
from app.services.camera_session_manager import (
    CameraSessionManager,
    ClientSessionEndedError,
    SessionAlreadyActiveError,
    SessionBusyError,
    SessionStatus,
    StallReason,
)

UMBRAL = 0.15


# ── Cámara simulada con comportamientos ──────────────────────────────────────

class CameraStats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.opens = 0
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
            self.active -= 1


class FakeCapture:
    """
    Comportamientos:
      ok            entrega frames válidos
      empty         entrega frames vacíos (la cámara responde, pero sin imagen)
      error         el driver lanza una excepción al leer
      hang_once     la primera lectura tarda 0.3 s; después entrega frames
      hang_forever  la lectura se congela hasta el final de la prueba
    """

    is_opened = True

    def __init__(self, stats: CameraStats, behavior: str, fin: threading.Event) -> None:
        self._stats = stats
        self.behavior = behavior
        self._fin = fin
        self._reading = False
        self._first = True
        self.release_calls = 0
        stats.opened()

    def read_frame(self):
        self._reading = True
        try:
            if self.behavior == "hang_forever":
                self._fin.wait(timeout=10)
                return None
            if self.behavior == "hang_once" and self._first:
                self._first = False
                time.sleep(0.3)
            time.sleep(0.005)
            if self.behavior == "empty":
                return None
            if self.behavior == "error":
                raise RuntimeError("fallo simulado del driver")
            return np.zeros((8, 8, 3), dtype=np.uint8)
        finally:
            self._reading = False

    def release(self) -> None:
        if self._reading:
            self._stats.released_while_reading = True
        self.release_calls += 1
        if self.release_calls == 1:
            self._stats.closed()


class Plan(list):
    """Comportamientos, uno por apertura (None = la apertura falla). Vacío = 'ok'."""

    def __init__(self) -> None:
        super().__init__()
        self.fin = threading.Event()
        self.capturas: list[FakeCapture] = []


@pytest.fixture
def stats() -> CameraStats:
    return CameraStats()


@pytest.fixture
def plan(monkeypatch, stats):
    p = Plan()

    def fake_open_camera(source: str):
        behavior = p.pop(0) if p else "ok"
        if behavior is None:
            return None
        captura = FakeCapture(stats, behavior, p.fin)
        p.capturas.append(captura)
        return captura

    monkeypatch.setattr(manager_module, "open_camera", fake_open_camera)
    # Margen que la captura concede a una lectura en curso al detenerse
    monkeypatch.setattr(manager_module, "FRAME_STALE_TIMEOUT_S", 0.5)
    yield p
    p.fin.set()  # libera cualquier hilo que siga congelado


@pytest.fixture
def manager() -> CameraSessionManager:
    return CameraSessionManager(
        stale_timeout_s=UMBRAL,
        watchdog_interval_s=0.02,
        recovery_attempts=3,
        recovery_backoff_s=0.01,
    )


def run(coro):
    return asyncio.run(coro)


def eventos(manager) -> list[str]:
    return [e["event"] for e in manager.get_lifecycle_status()["events"]]


async def esperar(condicion, limite: float = 3.0) -> None:
    fin = time.monotonic() + limite
    while not condicion():
        assert time.monotonic() < fin, "la condición no se cumplió a tiempo"
        await asyncio.sleep(0.01)


async def consumir_hasta_el_fin(manager, client_id: str, limite: float = 4.0) -> str:
    """Consume frames como el WebSocket hasta que la sesión del cliente termine."""
    fin = time.monotonic() + limite
    ultimo = 0
    try:
        while time.monotonic() < fin:
            packet = await asyncio.wait_for(manager.next_frame(client_id, ultimo), timeout=3)
            ultimo = packet.seq
    except ClientSessionEndedError as exc:
        return exc.code
    raise AssertionError("la sesión del cliente no terminó a tiempo")


# ── C1: distinguir activa de estancada ───────────────────────────────────────

def test_c1_camara_que_entrega_frames_esta_activa(manager, plan):
    async def escenario():
        await manager.connect_client("0", "c1")
        await asyncio.sleep(UMBRAL * 3)
        estado = manager.get_lifecycle_status()
        await manager.stop()
        return estado

    estado = run(escenario())

    assert estado["state"] == "streaming"
    assert estado["seconds_without_frames"] < UMBRAL
    assert "stalled" not in eventos(manager)


def test_c1_frames_vacios_se_detectan_como_no_frames(manager, plan):
    plan.extend(["empty", "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar(lambda: "stalled" in eventos(manager))
        await manager.stop()

    run(escenario())

    estancada = [e for e in manager.get_lifecycle_status()["events"] if e["event"] == "stalled"][0]
    assert estancada["reason"] == "no_frames"


def test_c1_lectura_congelada_se_detecta_como_read_timeout(manager, plan):
    plan.extend(["hang_once", "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar(lambda: "stalled" in eventos(manager))
        await manager.stop()

    run(escenario())

    estancada = [e for e in manager.get_lifecycle_status()["events"] if e["event"] == "stalled"][0]
    assert estancada["reason"] == "read_timeout"


def test_c1_una_lectura_normal_en_curso_no_se_confunde_con_una_congelada(manager, plan):
    """
    La captura casi siempre tiene una lectura en curso. El motivo no puede
    depender de eso, sino de cuánto lleva esa lectura. (Esta prueba fija el
    criterio sin depender de tiempos reales, que en Windows varían mucho.)
    """
    plan.append("hang_forever")

    async def escenario():
        await manager.start("0")
        session = manager.session
        ahora = time.monotonic()
        session.last_activity = ahora - UMBRAL * 3          # ya pasó el umbral

        session.reading_since = ahora - 0.01                # lectura normal, recién iniciada
        motivo_lectura_normal = manager.check_stall()

        session.reading_since = ahora - UMBRAL * 3          # lectura que no termina
        motivo_lectura_congelada = manager.check_stall()

        session.reading_since = None                        # sin lectura en curso
        motivo_sin_lectura = manager.check_stall()

        plan.fin.set()
        await manager.stop()
        return motivo_lectura_normal, motivo_lectura_congelada, motivo_sin_lectura

    normal, congelada, sin_lectura = run(escenario())

    assert normal == StallReason.NO_FRAMES
    assert congelada == StallReason.READ_TIMEOUT
    assert sin_lectura == StallReason.NO_FRAMES


def test_c1_un_frame_vacio_aislado_no_cierra_la_conexion(manager, plan):
    """Antes de M10, el primer frame vacío terminaba la captura."""
    plan.append("error")  # cada lectura falla, pero dentro del umbral no pasa nada

    async def escenario():
        await manager.connect_client("0", "c1")
        await asyncio.sleep(UMBRAL / 2)
        estado = manager.state
        perdidos = manager.session.metrics.frames_dropped
        await manager.stop()
        return estado, perdidos

    estado, perdidos = run(escenario())

    assert estado == SessionStatus.STREAMING
    assert perdidos > 0


def test_c1_tambien_se_vigila_sin_cliente(manager, plan):
    """La captura corre aunque no haya cliente, así que la vigilancia también."""
    plan.extend(["empty", "ok"])

    async def escenario():
        await manager.start("0")
        await esperar(lambda: "recovered" in eventos(manager))
        await manager.stop()

    run(escenario())

    estancada = [e for e in manager.get_lifecycle_status()["events"] if e["event"] == "stalled"][0]
    assert estancada["client_id"] is None


# ── C2: recuperación controlada ──────────────────────────────────────────────

def test_c2_recupera_y_el_mismo_cliente_sigue_recibiendo(manager, plan, stats):
    plan.extend(["empty", "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar(lambda: "recovered" in eventos(manager))
        frame = (await asyncio.wait_for(manager.next_frame("c1"), timeout=2)).frame
        cliente = manager.session.active_client
        await manager.stop()
        return frame, cliente

    frame, cliente = run(escenario())

    assert frame is not None
    assert cliente == "c1"
    assert stats.opens == 2
    assert stats.max_active == 1  # la vieja se cerró antes de abrir la nueva


def test_c2_recupera_lectura_congelada_que_termina_dentro_del_margen(manager, plan, stats):
    plan.extend(["hang_once", "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar(lambda: "recovered" in eventos(manager))
        await manager.stop()

    run(escenario())

    assert stats.released_while_reading is False
    assert stats.max_active == 1


def test_c2_reintenta_la_apertura_con_esperas_crecientes(manager, plan):
    plan.extend(["empty", None, None, "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar(lambda: "recovered" in eventos(manager))
        intentos = manager.session.recovery.last_attempts
        await manager.stop()
        return intentos

    assert run(escenario()) == 3


def test_c2_si_no_logra_reabrir_cierra_y_avisa_camera_stalled(manager, plan, stats):
    plan.extend(["empty", None, None, None])

    async def escenario():
        await manager.connect_client("0", "c1")
        return await consumir_hasta_el_fin(manager, "c1")

    codigo = run(escenario())

    assert codigo == "CAMERA_STALLED"
    assert manager.state == SessionStatus.IDLE
    assert stats.active == 0
    assert eventos(manager)[-4:] == [
        "stalled", "recovery_failed", "client_disconnected", "stopped",
    ]


def test_c2_se_rinde_si_tras_recuperar_sigue_sin_frames(manager, plan, stats):
    plan.extend(["empty"] * 10)  # cada reapertura funciona, pero nunca hay imagen

    async def escenario():
        await manager.connect_client("0", "c1")
        return await consumir_hasta_el_fin(manager, "c1")

    codigo = run(escenario())

    assert codigo == "CAMERA_STALLED"
    assert eventos(manager).count("recovered") == manager.recovery_attempts
    fallida = [e for e in manager.get_lifecycle_status()["events"] if e["event"] == "recovery_failed"][0]
    assert "sin frames tras 3 recuperaciones" in fallida["reason"]
    assert stats.active == 0
    assert all(c.release_calls == 1 for c in plan.capturas)


# ── C3: actividad y motivo registrados ───────────────────────────────────────

def test_c3_estado_expone_actividad_y_recuperacion(manager, plan):
    plan.extend(["empty", "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        inicial = manager.get_lifecycle_status()["last_activity_ts"]
        await esperar(lambda: "recovered" in eventos(manager))
        await esperar(lambda: manager.session.metrics.frames_total > 0)
        estado = manager.get_lifecycle_status()
        await manager.stop()
        return inicial, estado

    inicial, estado = run(escenario())

    assert estado["stale_timeout_s"] == UMBRAL
    assert estado["last_activity_ts"] > inicial
    assert estado["seconds_without_frames"] < UMBRAL
    recuperacion = estado["recovery"]
    assert recuperacion["total"] == 1
    assert recuperacion["last_reason"] == "no_frames"
    assert recuperacion["last_attempts"] == 1
    assert recuperacion["last_result"] == "recovered"
    assert recuperacion["consecutive"] == 0  # volvió a llegar imagen
    recuperada = [e for e in estado["events"] if e["event"] == "recovered"][0]
    assert recuperada["client_id"] == "c1"
    assert recuperada["reason"] == "no_frames; intento 1"


# ── C4: se conserva el límite de una sesión y un cliente ─────────────────────

def test_c4_durante_la_recuperacion_nadie_mas_entra(manager, plan, stats):
    manager.recovery_backoff_s = 0.2
    plan.extend(["empty", "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar(lambda: manager.state == SessionStatus.RECOVERING)
        resultados = await asyncio.gather(
            manager.connect_client("0", "intruso"),
            manager.start("0"),
            return_exceptions=True,
        )
        await esperar(lambda: "recovered" in eventos(manager))
        cliente = manager.session.active_client
        await manager.stop()
        return resultados, cliente

    resultados, cliente = run(escenario())

    # Las operaciones esperaron a que terminara la recuperación y la sesión seguía ocupada
    assert isinstance(resultados[0], SessionBusyError)
    assert isinstance(resultados[1], SessionAlreadyActiveError)
    assert cliente == "c1"
    assert stats.max_active == 1


def test_c4_lectura_congelada_no_abre_una_segunda_camara(manager, plan, stats):
    plan.extend(["hang_forever", "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        codigo = await consumir_hasta_el_fin(manager, "c1")
        abiertas_al_fallar = stats.opens
        liberaciones_al_fallar = plan.capturas[0].release_calls
        plan.fin.set()  # el driver por fin responde
        await esperar(lambda: plan.capturas[0].release_calls == 1)
        return codigo, abiertas_al_fallar, liberaciones_al_fallar

    codigo, abiertas, liberaciones = run(escenario())

    assert codigo == "CAMERA_STALLED"
    assert abiertas == 1          # nunca se intentó abrir otra
    assert liberaciones == 0      # no se cerró a mitad de la lectura
    assert stats.released_while_reading is False
    fallida = [e for e in manager.get_lifecycle_status()["events"] if e["event"] == "recovery_failed"][0]
    assert fallida["reason"] == "read_timeout; lectura congelada; cierre diferido"


def test_c4_detener_durante_la_recuperacion_deja_todo_cerrado(manager, plan, stats):
    manager.recovery_backoff_s = 0.2
    plan.extend(["empty", "ok"])

    async def escenario():
        await manager.connect_client("0", "c1")
        await esperar(lambda: manager.state == SessionStatus.RECOVERING)
        await manager.stop()  # espera a que termine la recuperación

    run(escenario())

    assert manager.state == SessionStatus.IDLE
    assert stats.active == 0
    assert stats.max_active == 1


def test_c4_cerrar_la_sesion_no_deja_vigilantes_pendientes(manager, plan):
    async def escenario():
        await manager.connect_client("0", "c1")
        await asyncio.sleep(0.05)
        await manager.shutdown()
        return asyncio.all_tasks() - {asyncio.current_task()}

    assert run(escenario()) == set()


# ── De punta a punta por WebSocket ───────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, manager, plan):
    monkeypatch.setattr(stream_router, "camera_session_manager", manager)
    monkeypatch.setattr(cameras_router, "camera_session_manager", manager)
    app = FastAPI()
    app.include_router(stream_router.router)
    app.include_router(cameras_router.router)
    with TestClient(app) as test_client:
        yield test_client


def test_ws_el_cliente_sobrevive_a_la_recuperacion(client, plan):
    plan.extend(["empty", "ok"])

    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        assert ws.receive_json()["connected"] is True
        # El primer frame llega solo cuando la cámara ya se recuperó
        frame = ws.receive_bytes()
        estado = client.get("/cameras/session").json()

    longitud = int.from_bytes(frame[:4], "big")
    assert json.loads(frame[4:4 + longitud])["connected"] is True
    assert estado["recovery"]["last_result"] == "recovered"
    assert estado["state"] == "streaming"


def test_ws_recuperacion_fallida_avisa_camera_stalled_con_1011(client, plan):
    plan.extend(["empty", None, None, None])

    with client.websocket_connect("/ws/stream?camera_id=0") as ws:
        ws.receive_json()
        fin = ws.receive_json()
        cierre = ws.receive()

    assert fin["error"] == "CAMERA_STALLED"
    assert cierre["code"] == 1011
