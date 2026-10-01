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
    async def scenario():
        ws = FakeWebSocket()
        capture = FakeCapture(max_frames=3)
        manager = CameraSessionManager()
        await _serve_until_closed(ws, capture, manager)
        return ws, capture, manager

    ws, capture, manager = asyncio.run(scenario())

    assert ws.json_messages[-1]["connected"] is False
    assert ws.json_messages[-1]["error"] == "CAMERA_NO_FRAMES"
    assert ws.close_code == 1000
    assert capture.release_calls == 1
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
