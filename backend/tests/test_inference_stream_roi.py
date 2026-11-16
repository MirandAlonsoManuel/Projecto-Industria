"""
update_roi durante una sesión de /ws/inference-stream, sin hardware.

Cámara simulada e inferencia determinista (ver tests/stream_fakes.py). La
inferencia devuelve, junto al gris del frame, la ROI con la que se ejecutó, para
comprobar que cada mensaje informa la ROI realmente usada en ese frame.
"""

from __future__ import annotations

from app.services.stream_control import RoiOutOfFrame, StreamControl
from tests.stream_fakes import Stream, assert_in_sync, cameras, manager, wait_until  # noqa: F401

BOX_A = {"x1": 4, "y1": 6, "x2": 40, "y2": 30}
BOX_B = {"x1": 10, "y1": 10, "x2": 60, "y2": 45}


def marker_infer(frame, roi):
    return [
        {
            "class_id": int(frame[0, 0, 0]),
            "class_name": "marker",
            "confidence": 1.0,
            "bbox": {"x1": 0, "y1": 0, "x2": 5, "y2": 5},
            "roi_used": list(roi) if roi else None,
        }
    ]


def roi_stream(manager, infer=marker_infer, control=None, **kwargs) -> Stream:
    return Stream(manager, infer=infer, control=control or StreamControl(), **kwargs)


async def test_messages_report_the_roi_and_version_they_were_inferred_with(manager):
    stream = roi_stream(manager, every_n=1)
    frames = await stream.frames(3)
    await stream.disconnect()
    await manager.shutdown()
    assert all(meta["roi"] is None and meta["roi_version"] == 0 for meta, _ in frames)
    assert_in_sync(frames)


async def test_update_roi_applies_to_following_frames_without_touching_the_camera(manager, cameras):
    stream = roi_stream(manager, every_n=1)
    await stream.frames(2)

    stream.ws.client_send({"type": "update_roi", "request_id": "a", "roi": BOX_A})
    (ack,) = await stream.replies(1)
    assert ack["type"] == "roi_updated" and ack["roi"] == BOX_A and ack["roi_version"] == 1
    assert ack["request_id"] == "a"
    await wait_until(lambda: any(m["roi_version"] == 1 for m, _ in stream.ws.frames))

    stream.ws.client_send({"type": "update_roi", "request_id": "b", "roi": None})
    await stream.replies(2)
    await wait_until(lambda: any(m["roi_version"] == 2 for m, _ in stream.ws.frames))

    frames = stream.ws.frames
    for meta, _ in frames:
        # El mensaje informa la ROI con la que realmente se infirió ese frame
        expected = [BOX_A["x1"], BOX_A["y1"], BOX_A["x2"], BOX_A["y2"]] if meta["roi"] == BOX_A else None
        assert meta["roi"] in (None, BOX_A)
        for detection in meta["detections"]:
            assert detection["roi_used"] == expected
    versions = [meta["roi_version"] for meta, _ in frames]
    assert versions == sorted(versions)  # nunca se regresa a una configuración vieja

    assert len(cameras.opened) == 1  # ni se reabrió la cámara...
    assert cameras.opened[0].released == 0  # ...ni se cerró
    assert stream.ws.closed_code is None  # el socket sigue abierto

    await stream.disconnect()
    await manager.shutdown()
    assert cameras.opened[0].released == 1


async def test_consecutive_updates_are_confirmed_in_order(manager):
    stream = roi_stream(manager)
    await stream.frames(1)
    for index, box in enumerate((BOX_A, BOX_B, BOX_A), start=1):
        stream.ws.client_send({"type": "update_roi", "request_id": index, "roi": box})
    acks = await stream.replies(3)
    assert [a["roi_version"] for a in acks] == [1, 2, 3]
    assert [a["request_id"] for a in acks] == [1, 2, 3]
    await wait_until(lambda: stream.ws.frames[-1][0]["roi_version"] == 3)
    assert stream.ws.frames[-1][0]["roi"] == BOX_A
    await stream.disconnect()
    await manager.shutdown()


async def test_removing_the_roi_returns_to_the_full_frame(manager):
    stream = roi_stream(manager)
    await stream.frames(1)
    stream.ws.client_send({"type": "update_roi", "roi": BOX_A})
    stream.ws.client_send({"type": "update_roi", "roi": None})
    acks = await stream.replies(2)
    assert acks[1]["roi"] is None and acks[1]["roi_version"] == 2
    await wait_until(lambda: stream.ws.frames[-1][0]["roi_version"] == 2)
    last = stream.ws.frames[-1][0]
    assert last["roi"] is None and last["detections"][0]["roi_used"] is None
    await stream.disconnect()
    await manager.shutdown()


async def test_invalid_updates_are_recoverable_and_keep_the_last_valid_roi(manager):
    stream = roi_stream(manager)
    await stream.frames(2)
    stream.ws.client_send({"type": "update_roi", "roi": BOX_A})
    await stream.replies(1)

    stream.ws.client_send({"type": "update_roi", "roi": {**BOX_A, "x1": -3}})  # negativa
    stream.ws.client_send({"type": "update_roi", "roi": {"x1": 0, "y1": 0, "x2": 500, "y2": 20}})  # fuera
    stream.ws.client_send("esto no es json")
    stream.ws.client_send({"type": "mover_camara"})
    replies = await stream.replies(5)

    errors = replies[1:]
    assert [e["error"] for e in errors] == [
        "INVALID_ROI",
        "ROI_OUT_OF_FRAME",
        "INVALID_MESSAGE",
        "UNKNOWN_MESSAGE_TYPE",
    ]
    for error in errors:
        assert error["recoverable"] is True
        assert error["roi"] == BOX_A and error["roi_version"] == 1  # lo que sigue activo

    # El stream no se interrumpió y la ROI vigente es la última válida
    seen = len(stream.ws.frames)
    await wait_until(lambda: len(stream.ws.frames) >= seen + 3)
    for meta, _ in stream.ws.frames[seen:]:
        assert meta["roi"] == BOX_A and meta["roi_version"] == 1
    assert stream.ws.closed_code is None
    assert_in_sync(stream.ws.frames)
    await stream.disconnect()
    await manager.shutdown()


async def test_roi_out_of_frame_at_runtime_sends_empty_detections_and_keeps_streaming(manager):
    def always_out(frame, roi):
        raise RoiOutOfFrame("la ROI no cabe")

    stream = roi_stream(manager, infer=always_out)
    frames = await stream.frames(5)
    await stream.disconnect()
    await manager.shutdown()
    assert {meta["detections_status"] for meta, _ in frames} == {"roi_out_of_frame"}
    assert_in_sync(frames)


async def test_invalid_initial_roi_notifies_and_streams_the_full_frame(manager):
    control = StreamControl()
    control.set_initial_roi("-1,0,5,5")
    stream = roi_stream(manager, control=control)
    frames = await stream.frames(3)

    connected, notice = stream.ws.json_messages[:2]
    assert connected["connected"] is True
    assert notice["type"] == "error" and notice["error"] == "INVALID_ROI"
    assert notice["recoverable"] is True
    assert all(meta["roi"] is None for meta, _ in frames)
    await stream.disconnect()
    await manager.shutdown()


async def test_valid_initial_roi_is_used_from_the_first_frame(manager):
    control = StreamControl()
    control.set_initial_roi(x1=4, y1=6, x2=40, y2=30)
    stream = roi_stream(manager, control=control)
    frames = await stream.frames(2)
    assert all(meta["roi"] == BOX_A for meta, _ in frames)
    assert frames[0][0]["detections"][0]["roi_used"] == [4, 6, 40, 30]
    await stream.disconnect()
    await manager.shutdown()


async def test_control_without_inference_still_serves_video_and_accepts_update_roi(manager):
    stream = Stream(manager, infer=None, control=StreamControl())
    frames = await stream.frames(2)
    assert all(meta["detections_status"] == "disabled" and meta["detections"] == [] for meta, _ in frames)
    stream.ws.client_send({"type": "update_roi", "roi": BOX_A})
    (ack,) = await stream.replies(1)
    assert ack["roi_version"] == 1
    await stream.disconnect()
    await manager.shutdown()
