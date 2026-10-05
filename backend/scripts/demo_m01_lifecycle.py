"""Demostración reproducible de M01 sin cámara física ni red."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.camera_session_manager import (  # noqa: E402
    CameraSessionManager,
    SessionBusyError,
)


class DemoCapture:
    def __init__(self) -> None:
        self.release_calls = 0

    @property
    def is_opened(self) -> bool:
        return self.release_calls == 0

    def read_frame(self) -> np.ndarray:
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self) -> None:
        self.release_calls += 1


async def main() -> None:
    manager = CameraSessionManager()
    captures: list[DemoCapture] = []

    def open_fake_camera(_: str) -> DemoCapture:
        capture = DemoCapture()
        captures.append(capture)
        return capture

    with patch(
        "app.services.camera_session_manager.open_camera",
        side_effect=open_fake_camera,
    ):
        print("1. Estado inicial:", manager.get_status())

        first = await manager.acquire("0", "cliente-1")
        first.update_frame(first.capture.read_frame())
        print("2. Cliente 1 conectado:", manager.get_status())

        try:
            await manager.acquire("0", "cliente-2")
        except SessionBusyError as error:
            print("3. Cliente 2 rechazado:", error.code)

        await manager.release("cliente-1")
        print("4. Sesión liberada:", manager.get_status())

        await manager.acquire("0", "cliente-2")
        print("5. Cliente 2 reconectado:", manager.get_status())
        await manager.release("cliente-2")

    print(
        "6. Resumen:",
        {
            "aperturas": len(captures),
            "liberaciones": sum(c.release_calls for c in captures),
            "capturas_activas": sum(c.is_opened for c in captures),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
