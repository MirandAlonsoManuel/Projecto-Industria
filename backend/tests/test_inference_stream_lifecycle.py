"""
Ciclo de vida de /ws/inference-stream sobre la sesión centralizada, sin hardware.

Gestor de cámaras real (instancia nueva por prueba), cámara simulada y socket
falso (ver tests/stream_fakes.py). Cubre: un solo cliente, rechazo controlado,
liberación al desconectar, estado limpio al reconectar, fallo de reapertura y
conexiones simultáneas.
"""

from __future__ import annotations

import asyncio

from app.services.stream_control import StreamControl
from tests.stream_fakes import GRAY_TOLERANCE, Stream, cameras, manager  # noqa: F401

BOX = {"x1": 4, "y1": 6, "x2": 40, "y2": 30}


def marker_infer(frame, roi):
    return [
        {
            "class_id": int(frame[0, 0, 0]),
            "class_name": "marker",
            "confidence": 1.0,
            "bbox": {"x1": 0, "y1": 0, "x2": 5, "y2": 5},
        }
    ]


def connect(manager, **kwargs) -> Stream:
    return Stream(manager, infer=marker_infer, control=StreamControl(), **kwargs)


async def test_second_client_is_rejected_with_camera_busy_and_first_keeps_streaming(manager, cameras):
    first = connect(manager)
    await first.frames(2)

    second = connect(manager)
    await asyncio.wait_for(second.task, 5)
    rejection = second.ws.json_messages[0]
    assert rejection["connected"] is False and rejection["error"] == "CAMERA_BUSY"
    assert second.ws.closed_code == 1008

    seen = len(first.ws.frames)
    await first.frames(seen + 2)  # el primero no se vio afectado
    assert len(cameras.opened) == 1  # no se abrió un dispositivo adicional

    await first.disconnect()
    await manager.shutdown()


async def test_concurrent_connection_attempts_only_one_wins(manager, cameras):
    streams = [connect(manager) for _ in range(5)]
    await asyncio.sleep(0.4)

    winners = [s for s in streams if s.ws.json_messages and s.ws.json_messages[0].get("connected")]
    losers = [s for s in streams if s not in winners]
    assert len(winners) == 1
    for loser in losers:
        await asyncio.wait_for(loser.task, 5)
        assert loser.ws.json_messages[0]["error"] == "CAMERA_BUSY"
        assert loser.ws.closed_code == 1008
    assert len(cameras.opened) == 1  # un solo dispositivo, nunca uno extra

    await winners[0].disconnect()
    assert manager.is_busy is False
    await manager.shutdown()


async def test_disconnect_cancels_everything_and_closes_the_camera_once(manager, cameras):
    baseline = set(asyncio.all_tasks())
    stream = connect(manager)
    await stream.frames(3)
    await stream.disconnect()

    assert manager.is_busy is False and manager.session is None
    assert len(cameras.opened) == 1 and cameras.opened[0].released == 1
    await manager.shutdown()
    assert cameras.opened[0].released == 1  # el apagado no la cierra otra vez
    await asyncio.sleep(0.05)
    leftover = [t for t in asyncio.all_tasks() if t not in baseline and not t.done()]
    assert leftover == []  # sin tareas de captura, vigilancia, envío ni inferencia


async def test_a_new_connection_starts_clean(manager, cameras):
    first = connect(manager)
    await first.frames(2)
    first.ws.client_send({"type": "update_roi", "roi": BOX})
    await first.replies(1)
    await first.disconnect()

    second = connect(manager)
    frames = await second.frames(2)
    meta, gray = frames[0]
    assert meta["roi"] is None and meta["roi_version"] == 0  # sin la ROI de la conexión anterior
    # Sin el último frame de la sesión anterior: la primera imagen es la primera lectura de la cámara nueva
    assert abs(gray - 20) <= GRAY_TOLERANCE
    assert len(cameras.opened) == 2
    await second.disconnect()
    await manager.shutdown()


async def test_repeated_cycles_start_clean_each_time(manager, cameras):
    for _ in range(5):
        stream = connect(manager)
        frames = await stream.frames(2)
        assert frames[0][0]["roi"] is None and frames[0][0]["roi_version"] == 0
        stream.ws.client_send({"type": "update_roi", "roi": BOX})
        await stream.replies(1)
        await stream.disconnect()
        assert manager.is_busy is False

    assert len(cameras.opened) == 5
    assert [camera.released for camera in cameras.opened] == [1] * 5
    await manager.shutdown()


async def test_reopen_failure_is_reported_and_does_not_leave_the_session_busy(manager, cameras):
    first = connect(manager)
    await first.frames(1)
    await first.disconnect()

    cameras.fail_next = 1
    failing = connect(manager)
    await asyncio.wait_for(failing.task, 5)
    error = failing.ws.json_messages[0]
    assert error["connected"] is False and error["error"] == "CAMERA_UNAVAILABLE"
    assert failing.ws.closed_code == 1000
    assert manager.is_busy is False

    again = connect(manager)  # la siguiente conexión funciona
    await again.frames(2)
    await again.disconnect()
    assert len(cameras.opened) == 2
    await manager.shutdown()


async def test_a_failed_stream_frees_the_camera_for_the_next_client(manager, cameras):
    def broken(frame, roi):
        raise RuntimeError("modelo caído")

    failing = Stream(manager, infer=broken, control=StreamControl())
    await asyncio.wait_for(failing.task, 5)
    assert failing.ws.json_messages[-1]["error"] == "STREAM_ERROR"
    assert manager.is_busy is False
    assert cameras.opened[0].released == 1

    healthy = connect(manager)
    await healthy.frames(2)
    await healthy.disconnect()
    await manager.shutdown()
