"""
Pruebas del desacople entre captura y comunicación WebSocket.
Ejecutables sin hardware físico: la cámara y el WebSocket son dobles de prueba.

Ejecutar:
    cd backend
    pytest tests/test_stream_decoupling.py -v
"""

import asyncio
import json
import struct
import threading
import time
from unittest.mock import patch

import numpy as np

from app.services.camera_session_manager import CameraSessionManager, SessionStatus
from app.services.stream_runner import serve_camera_stream


# ── Dobles de prueba ──────────────────────────────────────────────────────────

class FakeCapture:
    """Cámara falsa: entrega un frame cada `read_delay` segundos."""

    def __init__(self, read_delay: float = 0.005, max_frames: int | None = None) -> None:
        self.read_delay = read_delay
        self.max_frames = max_frames
        self.reads = 0
        self.release_calls = 0
        self.is_opened = True

    def read_frame(self):
        time.sleep(self.read_delay)
        if self.max_frames is not None and self.reads >= self.max_frames:
            return None
        self.reads += 1
        return np.zeros((48, 64, 3), dtype=np.uint8)

    def release(self) -> None:
        self.release_calls += 1


class FakeWebSocket:
    """WebSocket falso con envío lento configurable."""

    def __init__(self, send_delay: float = 0.0) -> None:
        self.send_delay = send_delay
        self.json_messages: list[dict] = []
        self.frames: list[dict] = []  # metadatos + antigüedad al momento de enviar
        self.close_code: int | None = None
        self._disconnect = asyncio.Event()

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        self.json_messages.append(data)

    async def send_bytes(self, data: bytes) -> None:
        (json_len,) = struct.unpack(">I", data[:4])
        meta = json.loads(data[4 : 4 + json_len])
        meta["age"] = time.time() - meta["timestamp"]
        self.frames.append(meta)
        await asyncio.sleep(self.send_delay)

    async def receive(self) -> dict:
        await self._disconnect.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    def disconnect(self) -> None:
        self._disconnect.set()


async def _serve_for(ws, capture, manager, duration, **kwargs):
    """Atiende al cliente durante `duration` segundos y luego lo desconecta."""
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        task = asyncio.create_task(serve_camera_stream(ws, manager, "0", "listo", **kwargs))
        await asyncio.sleep(duration)
        session = manager.session
        snapshot = session.to_dict() if session is not None else None
        ws.disconnect()
        await asyncio.wait_for(task, timeout=5)
    return session, snapshot


async def _serve_until_closed(ws, capture, manager, **kwargs):
    """Atiende al cliente hasta que el servidor cierre por su cuenta."""
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        await asyncio.wait_for(
            serve_camera_stream(ws, manager, "0", "listo", **kwargs), timeout=5
        )


# ── Cliente lento ─────────────────────────────────────────────────────────────

def test_cliente_lento_no_bloquea_la_captura():
    async def scenario():
        ws = FakeWebSocket(send_delay=0.25)
        _, snapshot = await _serve_for(ws, FakeCapture(), CameraSessionManager(), duration=1.5)
        return ws, snapshot

    ws, snapshot = asyncio.run(scenario())
    captured = snapshot["metrics"]["frames_total"]
    sent = len(ws.frames)

    # El cliente solo pudo recibir ~6 frames; la captura siguió a su ritmo.
    assert sent <= 8
    assert captured >= 3 * sent
    assert snapshot["delivery"]["frames_skipped"] > 0


def test_cliente_lento_recibe_frames_recientes_sin_retraso_acumulado():
    async def scenario():
        ws = FakeWebSocket(send_delay=0.25)
        await _serve_for(ws, FakeCapture(), CameraSessionManager(), duration=1.5)
        return ws

    ws = asyncio.run(scenario())
    seqs = [f["seq"] for f in ws.frames]
    ages = [f["age"] for f in ws.frames]

    assert len(seqs) >= 3
    # La secuencia salta: se descartan los frames intermedios.
    assert all(b - a > 1 for a, b in zip(seqs[1:], seqs[2:]))
    # La antigüedad se mantiene acotada y no crece con el tiempo.
    assert max(ages) < 0.15


def test_cliente_rapido_recibe_todos_los_frames_en_orden():
    async def scenario():
        ws = FakeWebSocket()
        _, snapshot = await _serve_for(ws, FakeCapture(), CameraSessionManager(), duration=0.8)
        return ws, snapshot

    ws, snapshot = asyncio.run(scenario())
    seqs = [f["seq"] for f in ws.frames]

    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert snapshot["delivery"]["frames_skipped"] <= 2


# ── Desconexión y fin de captura ──────────────────────────────────────────────

def test_desconexion_cancela_tareas_y_libera_la_camara():
    async def scenario():
        ws = FakeWebSocket(send_delay=0.25)
        capture = FakeCapture()
        manager = CameraSessionManager()
        session, _ = await _serve_for(ws, capture, manager, duration=0.4)
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        return capture, manager, session, pending

    capture, manager, session, pending = asyncio.run(scenario())

    assert pending == set()
    assert session.capture_task is None
    assert session.frames.closed
    assert capture.release_calls == 1
    assert manager.session is None
    assert manager.get_status()["status"] == SessionStatus.IDLE.value


def test_desconexion_detiene_la_captura_antes_de_liberar():
    async def scenario():
        ws = FakeWebSocket()
        capture = FakeCapture()
        await _serve_for(ws, capture, CameraSessionManager(), duration=0.3)
        reads_al_liberar = capture.reads
        await asyncio.sleep(0.2)
        return capture, reads_al_liberar

    capture, reads_al_liberar = asyncio.run(scenario())

    # Tras liberar no se vuelve a leer de la cámara.
    assert capture.reads == reads_al_liberar


def test_camara_sin_frames_notifica_y_cierra():
    """
    M10: un frame vacío ya no cierra la conexión de inmediato. Si la cámara deja
    de producir frames, el vigilante intenta recuperarla; si tras las
    recuperaciones sigue sin frames, se notifica CAMERA_STALLED y se cierra.
    """
    capturas: list[FakeCapture] = []

    def abrir(_source):
        # La primera entrega 3 frames; las reaperturas ya no entregan ninguno
        captura = FakeCapture(max_frames=3 if not capturas else 0)
        capturas.append(captura)
        return captura

    async def scenario():
        ws = FakeWebSocket()
        manager = CameraSessionManager(
            stale_timeout_s=0.1, watchdog_interval_s=0.02, recovery_backoff_s=0.01
        )
        with patch("app.services.camera_session_manager.open_camera", side_effect=abrir):
            await asyncio.wait_for(serve_camera_stream(ws, manager, "0", "listo"), timeout=5)
        await asyncio.sleep(0.05)
        return ws, manager

    ws, manager = asyncio.run(scenario())

    assert ws.json_messages[-1]["connected"] is False
    assert ws.json_messages[-1]["error"] == "CAMERA_STALLED"
    assert ws.close_code == 1011
    assert len(capturas) > 1  # hubo reaperturas antes de rendirse
    assert all(c.release_calls == 1 for c in capturas)  # cada captura se cerró una vez
    assert manager.session is None


# ── Inferencia ────────────────────────────────────────────────────────────────

def test_inferencia_lenta_no_frena_el_video():
    def slow_infer(frame):
        time.sleep(0.3)
        return [{"class_id": 1}]

    async def scenario():
        ws = FakeWebSocket()
        await _serve_for(
            ws, FakeCapture(), CameraSessionManager(), duration=1.5, infer=slow_infer
        )
        return ws

    ws = asyncio.run(scenario())

    assert len(ws.frames) >= 15
    assert ws.frames[-1]["detections"] == [{"class_id": 1}]


def test_error_de_inferencia_cierra_con_1011():
    def failing_infer(frame):
        raise ValueError("ROI está fuera de los límites de la imagen.")

    async def scenario():
        ws = FakeWebSocket()
        capture = FakeCapture()
        await _serve_until_closed(ws, capture, CameraSessionManager(), infer=failing_infer)
        return ws, capture

    ws, capture = asyncio.run(scenario())

    assert ws.close_code == 1011
    assert ws.json_messages[-1]["error"] == "STREAM_ERROR"
    assert ws.json_messages[-1]["description"] == "ROI está fuera de los límites de la imagen."
    assert capture.release_calls == 1


# ── Liberación con read_frame() bloqueado ─────────────────────────────────────

class BlockingCapture:
    """Cámara falsa cuya lectura se queda bloqueada hasta llamar a `unblock()`."""

    def __init__(self, frames_before_block: int = 2) -> None:
        self.frames_before_block = frames_before_block
        self.reads = 0
        self.reading = False
        self.release_calls = 0
        self.released_during_read = False
        self.blocked = threading.Event()
        self._unblock = threading.Event()

    def read_frame(self):
        self.reading = True
        try:
            if self.reads >= self.frames_before_block:
                self.blocked.set()
                self._unblock.wait()
            else:
                time.sleep(0.005)
            self.reads += 1
            return np.zeros((48, 64, 3), dtype=np.uint8)
        finally:
            self.reading = False

    def release(self) -> None:
        self.release_calls += 1
        if self.reading:
            self.released_during_read = True

    def unblock(self) -> None:
        self._unblock.set()


async def _wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("La condición esperada no se cumplió a tiempo")
        await asyncio.sleep(0.01)


async def _acquire_and_block(manager, capture, client_id="cliente-1"):
    """Abre la sesión y espera a que la lectura de la cámara quede bloqueada."""
    with patch("app.services.camera_session_manager.open_camera", return_value=capture):
        await manager.acquire("0", client_id)
    await _wait_until(capture.blocked.is_set)


def test_release_no_cierra_la_camara_mientras_read_frame_sigue_bloqueado():
    async def scenario():
        capture = BlockingCapture()
        manager = CameraSessionManager()
        try:
            await _acquire_and_block(manager, capture)
            released = await manager.release("cliente-1")
            # Se da margen de sobra: el cierre no debe ocurrir por tiempo.
            await asyncio.sleep(0.3)
            durante_bloqueo = (released, capture.release_calls, capture.reading, manager.is_busy)

            capture.unblock()
            await _wait_until(lambda: capture.release_calls == 1)
            await asyncio.sleep(0.05)
        finally:
            capture.unblock()
        return capture, durante_bloqueo

    with patch("app.services.camera_session_manager.FRAME_STALE_TIMEOUT_S", 0.1):
        capture, durante_bloqueo = asyncio.run(scenario())

    released, release_calls, reading, is_busy = durante_bloqueo
    assert released is True
    assert reading is True
    assert release_calls == 0  # la lectura sigue en curso: la cámara no se cierra
    assert is_busy is False  # la sesión no queda secuestrada por la lectura

    # Al terminar la lectura, la cámara se cierra exactamente una vez.
    assert capture.release_calls == 1
    assert capture.released_during_read is False


def test_shutdown_no_cierra_la_camara_mientras_read_frame_sigue_bloqueado():
    async def scenario():
        capture = BlockingCapture()
        manager = CameraSessionManager()
        try:
            await _acquire_and_block(manager, capture)
            await manager.shutdown()
            release_calls_bloqueado = capture.release_calls

            capture.unblock()
            await _wait_until(lambda: capture.release_calls == 1)
        finally:
            capture.unblock()
        return capture, release_calls_bloqueado

    with patch("app.services.camera_session_manager.FRAME_STALE_TIMEOUT_S", 0.1):
        capture, release_calls_bloqueado = asyncio.run(scenario())

    assert release_calls_bloqueado == 0
    assert capture.release_calls == 1
    assert capture.released_during_read is False


def test_desconexion_con_read_frame_bloqueado_libera_la_sesion_sin_cerrar_a_mitad():
    async def scenario():
        ws = FakeWebSocket()
        capture = BlockingCapture()
        manager = CameraSessionManager()
        try:
            with patch(
                "app.services.camera_session_manager.open_camera", return_value=capture
            ):
                task = asyncio.create_task(serve_camera_stream(ws, manager, "0", "listo"))
                await _wait_until(capture.blocked.is_set)
                ws.disconnect()
                await asyncio.wait_for(task, timeout=5)
            estado = (manager.get_status()["status"], capture.release_calls)

            capture.unblock()
            await _wait_until(lambda: capture.release_calls == 1)
        finally:
            capture.unblock()
        return capture, estado

    with patch("app.services.camera_session_manager.FRAME_STALE_TIMEOUT_S", 0.1):
        capture, estado = asyncio.run(scenario())

    assert estado == (SessionStatus.IDLE.value, 0)
    assert capture.release_calls == 1
    assert capture.released_during_read is False


def test_release_cierra_de_inmediato_si_la_lectura_termina_dentro_del_margen():
    async def scenario():
        capture = FakeCapture(read_delay=0.05)
        manager = CameraSessionManager()
        with patch("app.services.camera_session_manager.open_camera", return_value=capture):
            await manager.acquire("0", "cliente-1")
        await asyncio.sleep(0.12)
        await manager.release("cliente-1")
        return capture

    capture = asyncio.run(scenario())

    assert capture.release_calls == 1
