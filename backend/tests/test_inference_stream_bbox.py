"""
Tamaño del frame original en cada mensaje del stream (sin hardware ni FastAPI).

La normalización de las cajas (recorte a los límites, ROI desplazada, cajas
parciales) está en test_detections.py; aquí se comprueba que el mensaje que
llega al cliente declara el tamaño del frame sobre el que están esas cajas.
"""

from __future__ import annotations

import json
import struct

from app.services.stream_protocol import encode_ws_message
from tests.stream_fakes import HEIGHT, WIDTH, Stream, cameras, manager  # noqa: F401


def _frame():
    import numpy as np

    return np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)


def _meta(message: bytes) -> dict:
    size = struct.unpack(">I", message[:4])[0]
    return json.loads(message[4 : 4 + size])


def test_extra_fields_are_added_to_the_metadata():
    meta = _meta(encode_ws_message(_frame(), [], 30.0, "0", 70, 5, 123.0, {"frame_width": 64, "frame_height": 48}))
    assert meta["frame_width"] == 64 and meta["frame_height"] == 48


def test_extra_fields_never_override_the_core_metadata():
    meta = _meta(encode_ws_message(_frame(), [], 30.0, "0", 70, 5, 123.0, {"seq": 999, "connected": False, "x": 1}))
    assert meta["seq"] == 5 and meta["connected"] is True and meta["x"] == 1


def test_messages_without_extra_keep_the_previous_format():
    meta = _meta(encode_ws_message(_frame(), [], 30.0, "0", 70, 5, 123.0))
    assert "frame_width" not in meta and meta["seq"] == 5


async def test_plain_stream_messages_declare_the_original_frame_size(manager):
    stream = Stream(manager)  # sin inferencia (como /ws/stream)
    frames = await stream.frames(3)
    await stream.disconnect()
    await manager.shutdown()
    for meta, _ in frames:
        assert meta["frame_width"] == WIDTH and meta["frame_height"] == HEIGHT


async def test_inference_stream_messages_declare_the_original_frame_size(manager):
    stream = Stream(manager, infer=lambda frame: [], every_n=1)
    frames = await stream.frames(3)
    await stream.disconnect()
    await manager.shutdown()
    for meta, _ in frames:
        assert meta["frame_width"] == WIDTH and meta["frame_height"] == HEIGHT
