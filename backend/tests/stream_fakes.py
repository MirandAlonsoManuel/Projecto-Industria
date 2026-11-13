"""
Dobles de prueba compartidos para el stream de inferencia, sin hardware.

- Cámara simulada: `FakeCamera` entrega frames de un gris uniforme distinto.
- Gestor: los fixtures `cameras` y `manager` crean una instancia NUEVA de
  CameraSessionManager y sustituyen `open_camera` con monkeypatch. No se toca el
  singleton global ni el lifespan, así que no interfiere con otras pruebas.
- Socket: `FakeWebSocket`, sin servidor.

Se importa desde las pruebas con `from tests.stream_fakes import ...`
(`pythonpath = .` en pytest.ini).
"""

from __future__ import annotations

import asyncio
import json
import struct
import time

import cv2
import numpy as np
import pytest

from app.services import camera_session_manager as csm_module
from app.services.camera_session_manager import CameraSessionManager
from app.services.stream_runner import serve_camera_stream

WIDTH, HEIGHT = 64, 48
GRAY_TOLERANCE = 4  # el JPEG es con pérdida; los grises consecutivos difieren en 10


class FakeCamera:
    """Cada lectura devuelve un gris uniforme distinto (10, 20, ... 240)."""

    def __init__(self) -> None:
        self.reads = 0
        self.released = 0

    def read_frame(self):
        self.reads += 1
        value = 10 * (self.reads % 24 + 1)
        return np.full((HEIGHT, WIDTH, 3), value, dtype=np.uint8)

    def release(self) -> None:
        self.released += 1

    @property
    def is_opened(self) -> bool:
        return True


class FakeCameras:
    """Sustituye a `open_camera`: registra cada apertura y permite fallar la siguiente."""

    def __init__(self) -> None:
        self.opened: list[FakeCamera] = []
        self.fail_next = 0

    def __call__(self, camera_id):
        if self.fail_next:
            self.fail_next -= 1
            return None
        camera = FakeCamera()
        self.opened.append(camera)
        return camera


class FakeWebSocket:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[tuple[str, object]] = []
        self.accepted = False
        self.closed_code = None

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent.append(("json", data))

    async def send_bytes(self, data):
        self.sent.append(("bytes", data))

    async def close(self, code=1000):
        self.closed_code = code

    async def receive(self):
        return await self.inbox.get()

    # -- lado cliente --
    def client_send(self, payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.inbox.put_nowait({"type": "websocket.receive", "text": text})

    def client_disconnect(self) -> None:
        self.inbox.put_nowait({"type": "websocket.disconnect", "code": 1000})

    @property
    def json_messages(self) -> list[dict]:
        return [data for kind, data in self.sent if kind == "json"]

    @property
    def frames(self) -> list[tuple[dict, int]]:
        """(metadatos, gris del JPEG) de cada mensaje binario."""
        result = []
        for kind, data in self.sent:
            if kind != "bytes":
                continue
            size = struct.unpack(">I", data[:4])[0]
            meta = json.loads(data[4 : 4 + size])
            image = cv2.imdecode(np.frombuffer(data[4 + size :], np.uint8), cv2.IMREAD_COLOR)
            result.append((meta, int(image[0, 0, 0])))
        return result


async def wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Se agotó el tiempo esperando la condición.")
        await asyncio.sleep(0.01)


class Stream:
    """Un cliente conectado a serve_camera_stream.

    `timeout` es holgado por defecto para que las pruebas no dependan de la
    velocidad de la máquina; la prueba del plazo de producción lo indica
    explícitamente. `control` solo se pasa si se indica.
    """

    def __init__(self, manager, infer=None, every_n=1, timeout=2.0, control=None, camera_id="0"):
        self.ws = FakeWebSocket()
        self.control = control
        options = {"inference_timeout_s": timeout}
        if control is not None:
            options["control"] = control
        self.task = asyncio.create_task(
            serve_camera_stream(
                self.ws,
                manager,
                camera_id,
                "Cámara detectada. Iniciando inferencia.",
                infer=infer,
                infer_every_n_frames=every_n,
                **options,
            )
        )

    async def frames(self, n: int):
        await wait_until(lambda: len(self.ws.frames) >= n)
        return self.ws.frames

    async def replies(self, n: int):
        """Mensajes JSON posteriores al "connected" inicial."""
        await wait_until(lambda: len(self.ws.json_messages) >= n + 1)
        return self.ws.json_messages[1:]

    async def disconnect(self):
        self.ws.client_disconnect()
        await asyncio.wait_for(self.task, 5)


def assert_in_sync(frames) -> None:
    """Toda detección `ok` debe pertenecer al frame (gris) del propio mensaje."""
    for meta, gray in frames:
        if meta["detections_status"] == "ok":
            for detection in meta["detections"]:
                assert abs(detection["class_id"] - gray) <= GRAY_TOLERANCE, (
                    f"Desfase en seq={meta['seq']}: detección del frame {detection['class_id']} "
                    f"sobre una imagen {gray}"
                )
        else:
            assert meta["detections"] == [], f"Detecciones en estado {meta['detections_status']}"


@pytest.fixture
def cameras(monkeypatch):
    fake = FakeCameras()
    monkeypatch.setattr(csm_module, "open_camera", fake)
    return fake


@pytest.fixture
def manager(cameras):
    return CameraSessionManager()
