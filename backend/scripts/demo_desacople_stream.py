"""
Demostración del desacople entre captura y comunicación WebSocket.

No necesita cámara ni servidor: usa una cámara simulada y un cliente
simulado cuyo envío tarda lo que se indique, contra el mismo código que
atiende /ws/stream en producción (serve_camera_stream).

Ejecutar:
    cd backend
    python scripts/demo_desacople_stream.py
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.camera_session_manager import CameraSessionManager  # noqa: E402
from app.services.stream_runner import serve_camera_stream  # noqa: E402

DURATION_S = 3.0


class SimulatedCamera:
    is_opened = True

    def __init__(self) -> None:
        self.release_calls = 0

    def read_frame(self) -> np.ndarray:
        time.sleep(0.005)
        return np.zeros((480, 640, 3), dtype=np.uint8)

    def release(self) -> None:
        self.release_calls += 1


class SimulatedClient:
    """Cliente WebSocket cuyo envío tarda `send_delay` segundos."""

    def __init__(self, send_delay: float) -> None:
        self.send_delay = send_delay
        self.ages: list[float] = []
        self._disconnect = asyncio.Event()

    async def accept(self) -> None:
        pass

    async def send_json(self, data: dict) -> None:
        pass

    async def send_bytes(self, data: bytes) -> None:
        (json_len,) = struct.unpack(">I", data[:4])
        meta = json.loads(data[4 : 4 + json_len])
        self.ages.append(time.time() - meta["timestamp"])
        await asyncio.sleep(self.send_delay)

    async def receive(self) -> dict:
        await self._disconnect.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    async def close(self, code: int = 1000) -> None:
        pass

    def disconnect(self) -> None:
        self._disconnect.set()


async def run_scenario(label: str, send_delay: float) -> None:
    camera = SimulatedCamera()
    client = SimulatedClient(send_delay)
    manager = CameraSessionManager()

    with patch("app.services.camera_session_manager.open_camera", return_value=camera):
        task = asyncio.create_task(serve_camera_stream(client, manager, "0", "listo"))
        await asyncio.sleep(DURATION_S)
        status = manager.get_status()
        client.disconnect()
        await task

    metrics, delivery = status["metrics"], status["delivery"]
    pending = len(asyncio.all_tasks() - {asyncio.current_task()})

    print(f"\n{label} (envío de {send_delay * 1000:.0f} ms por frame, {DURATION_S:.0f} s)")
    print(f"  frames capturados ........ {metrics['frames_total']}")
    print(f"  FPS de captura ........... {metrics['fps_current']}")
    print(f"  frames enviados .......... {delivery['frames_sent']}")
    print(f"  frames saltados .......... {delivery['frames_skipped']}")
    print(f"  antigüedad máx. al enviar  {max(client.ages) * 1000:.0f} ms")
    print(f"  antigüedad del último .... {client.ages[-1] * 1000:.0f} ms")
    print("  tras desconectar:")
    print(f"    estado de la sesión .... {manager.get_status()['status']}")
    print(f"    cámara liberada ........ {camera.release_calls} vez")
    print(f"    tareas pendientes ...... {pending}")


async def main() -> None:
    await run_scenario("Cliente rápido", send_delay=0.0)
    await run_scenario("Cliente lento", send_delay=0.25)
    await run_scenario("Cliente muy lento", send_delay=1.0)


if __name__ == "__main__":
    asyncio.run(main())
