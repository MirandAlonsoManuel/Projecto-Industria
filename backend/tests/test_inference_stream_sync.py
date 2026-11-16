"""
Sincronía entre el frame y sus detecciones en /ws/inference-stream, sin hardware.

Cámara simulada: cada frame es un gris uniforme distinto. Inferencia
determinista: devuelve como `class_id` el gris del frame que recibió. Comparar
esa detección con el JPEG del MISMO mensaje demuestra si pertenecen al mismo
frame; cualquier desfase hace fallar `assert_in_sync`.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.services.stream_runner import INFERENCE_TIMEOUT_S
from tests.stream_fakes import (  # noqa: F401
    HEIGHT,
    WIDTH,
    Stream,
    assert_in_sync,
    cameras,
    manager,
    wait_until,
)


def marker_infer(frame):
    """Determinista: la detección declara el gris del frame que recibió."""
    return [
        {
            "class_id": int(frame[0, 0, 0]),
            "class_name": "marker",
            "confidence": 1.0,
            "bbox": {"x1": 0, "y1": 0, "x2": 5, "y2": 5},
        }
    ]


async def test_the_sync_checker_really_detects_a_mismatch():
    good = ({"seq": 1, "detections_status": "ok", "detections": [{"class_id": 100}]}, 100)
    stale = ({"seq": 2, "detections_status": "ok", "detections": [{"class_id": 100}]}, 110)
    leaked = ({"seq": 3, "detections_status": "timeout", "detections": [{"class_id": 100}]}, 120)
    assert_in_sync([good])
    with pytest.raises(AssertionError, match="Desfase"):
        assert_in_sync([good, stale])
    with pytest.raises(AssertionError, match="Detecciones en estado"):
        assert_in_sync([leaked])


async def test_every_message_has_image_and_detections_of_the_same_frame(manager):
    stream = Stream(manager, infer=marker_infer, every_n=1)
    frames = await stream.frames(8)
    await stream.disconnect()
    await manager.shutdown()

    seqs = [meta["seq"] for meta, _ in frames]
    assert seqs == sorted(set(seqs))  # estrictamente crecientes, sin repetir
    for meta, _ in frames:
        assert meta["captured_at"] == meta["timestamp"]
        assert meta["frame_width"] == WIDTH and meta["frame_height"] == HEIGHT
        assert meta["detections_status"] == "ok"
    assert_in_sync(frames)


async def test_slow_inference_keeps_streaming_and_never_reuses_old_detections(manager):
    calls = []

    def sometimes_slow(frame):
        calls.append(1)
        if len(calls) == 2:
            time.sleep(0.4)  # la segunda inferencia se retrasa mucho
        return marker_infer(frame)

    def timeout_seen_then_ok() -> bool:
        statuses = [m["detections_status"] for m, _ in stream.ws.frames]
        return "timeout" in statuses and "ok" in statuses[statuses.index("timeout") :]

    stream = Stream(manager, infer=sometimes_slow, every_n=1, timeout=0.05)
    await wait_until(timeout_seen_then_ok)
    await stream.disconnect()
    await manager.shutdown()

    statuses = [meta["detections_status"] for meta, _ in stream.ws.frames]
    assert "timeout" in statuses and "busy" in statuses  # el video no se detuvo
    assert_in_sync(stream.ws.frames)  # ninguna detección vieja sobre una imagen nueva


async def test_slow_inference_does_not_brake_the_video_with_the_production_timeout(manager):
    # Un modelo de 0.3 s no puede bajar el video al ritmo del modelo (4 fps).
    def slow(frame):
        time.sleep(0.3)
        return marker_infer(frame)

    stream = Stream(manager, infer=slow, every_n=1, timeout=INFERENCE_TIMEOUT_S)
    await asyncio.sleep(1.5)
    frames = stream.ws.frames
    await stream.disconnect()
    await manager.shutdown()
    assert len(frames) >= 15
    assert_in_sync(frames)  # y aun así ninguna detección vieja sobre una imagen nueva


async def test_fast_inference_delivers_detections_with_the_production_timeout(manager):
    stream = Stream(manager, infer=marker_infer, every_n=1, timeout=INFERENCE_TIMEOUT_S)
    await wait_until(lambda: any(m["detections_status"] == "ok" for m, _ in stream.ws.frames))
    frames = stream.ws.frames
    await stream.disconnect()
    await manager.shutdown()
    assert_in_sync(frames)


async def test_only_one_inference_is_ever_in_flight(manager):
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def slow(frame):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.15)
        with lock:
            state["now"] -= 1
        return marker_infer(frame)

    stream = Stream(manager, infer=slow, every_n=1, timeout=0.03)
    await stream.frames(30)
    await stream.disconnect()
    await manager.shutdown()
    assert state["max"] == 1  # no se acumula cola de inferencias


async def test_infer_every_n_frames_marks_skipped_frames_instead_of_reusing(manager):
    stream = Stream(manager, infer=marker_infer, every_n=3)
    frames = await stream.frames(12)
    await stream.disconnect()
    await manager.shutdown()

    statuses = [meta["detections_status"] for meta, _ in frames]
    assert set(statuses) <= {"ok", "skipped"}
    assert "skipped" in statuses
    ok_seqs = [meta["seq"] for meta, _ in frames if meta["detections_status"] == "ok"]
    assert all(b - a >= 3 for a, b in zip(ok_seqs, ok_seqs[1:]))
    assert_in_sync(frames)


async def test_a_message_without_valid_detections_is_part_of_the_contract(manager):
    # Inferencia sin objetos: el estado es "ok" y la lista vacía. No es un error.
    stream = Stream(manager, infer=lambda frame: [], every_n=1)
    frames = await stream.frames(3)
    await stream.disconnect()
    await manager.shutdown()
    assert all(meta["detections_status"] == "ok" and meta["detections"] == [] for meta, _ in frames)


async def test_real_inference_failure_ends_the_stream_with_error_and_frees_the_camera(manager):
    def broken(frame):
        raise RuntimeError("modelo caído")

    stream = Stream(manager, infer=broken)
    await asyncio.wait_for(stream.task, 5)
    last = stream.ws.json_messages[-1]
    assert last["error"] == "STREAM_ERROR"
    assert stream.ws.closed_code == 1011
    assert manager.is_busy is False
    await manager.shutdown()


async def test_stream_without_inference_still_sends_video_with_empty_detections(manager):
    stream = Stream(manager)  # /ws/stream: sin inferencia, emisor clásico
    frames = await stream.frames(3)
    await stream.disconnect()
    await manager.shutdown()
    assert all(meta["detections"] == [] for meta, _ in frames)
