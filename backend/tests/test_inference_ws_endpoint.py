"""
/ws/inference-stream por el endpoint real (TestClient), sin hardware.

App mínima con SOLO este router y sin lifespan. Gestor de cámaras nuevo,
cámara simulada y `inference_service.localize` sustituido: nada global queda
modificado (monkeypatch lo restaura).
"""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.routers import inference as router_module  # noqa: E402
from app.services import camera_session_manager as csm_module  # noqa: E402
from app.services.camera_session_manager import CameraSessionManager  # noqa: E402

WIDTH, HEIGHT = 64, 48


class _Camera:
    def read_frame(self):
        return np.full((HEIGHT, WIDTH, 3), 100, dtype=np.uint8)

    def release(self) -> None:
        pass

    @property
    def is_opened(self) -> bool:
        return True


@pytest.fixture
def client(monkeypatch):
    seen = []

    def fake_localize(image, model_id, conf, iou, offset=(0, 0)):
        seen.append((image.shape[:2], offset))
        # Caja que se sale del frame por todos lados: el endpoint debe recortarla
        return "fake-model", [
            {
                "class_id": 1,
                "class_name": "pieza",
                "confidence": 0.9,
                "bbox": {"x1": -10.0, "y1": -10.0, "x2": 500.0, "y2": 500.0},
            }
        ]

    monkeypatch.setattr(csm_module, "open_camera", lambda camera_id: _Camera())
    monkeypatch.setattr(router_module, "camera_session_manager", CameraSessionManager())
    monkeypatch.setattr(router_module.inference_service, "localize", fake_localize)

    app = FastAPI()
    app.include_router(router_module.router)
    test_client = TestClient(app)  # sin `with`: no se ejecuta ningún lifespan
    test_client.localize_calls = seen
    return test_client


def _decode(data: bytes) -> dict:
    size = struct.unpack(">I", data[:4])[0]
    return json.loads(data[4 : 4 + size])


def _receive_until(ws, predicate, limit: int = 200):
    """Lee mensajes (texto o binario) hasta que `predicate(kind, payload)` sea verdadero."""
    for _ in range(limit):
        message = ws.receive()
        if message.get("bytes") is not None:
            kind, payload = "frame", _decode(message["bytes"])
        else:
            kind, payload = "json", json.loads(message["text"])
        if predicate(kind, payload):
            return payload
    raise AssertionError("No llegó el mensaje esperado.")


def test_boxes_are_clamped_to_the_original_frame_and_message_carries_its_size(client):
    with client.websocket_connect("/ws/inference-stream?infer_every_n_frames=1") as ws:
        assert ws.receive_json()["connected"] is True
        meta = _receive_until(ws, lambda kind, p: kind == "frame" and p["detections"])
    assert meta["frame_width"] == WIDTH and meta["frame_height"] == HEIGHT
    assert meta["detections"][0]["bbox"] == {"x1": 0.0, "y1": 0.0, "x2": float(WIDTH), "y2": float(HEIGHT)}


def test_roi_box_is_translated_to_the_original_frame_by_the_endpoint(client):
    # La ROI llega por la URL (formato x,y,ancho,alto); localize recibe el recorte y el offset.
    with client.websocket_connect("/ws/inference-stream?roi=4,6,36,24&infer_every_n_frames=1") as ws:
        ws.receive_json()
        meta = _receive_until(ws, lambda kind, p: kind == "frame" and p["detections"])
    assert ((24, 36), (4, 6)) in client.localize_calls
    # La caja falsa se sale del frame, así que sale recortada a sus límites
    assert meta["detections"][0]["bbox"]["x2"] == float(WIDTH)
