"""
Router WebSocket para streaming en tiempo real de frames de cámara.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.limits import TARGET_FPS
from app.services.camera_session_manager import (
    SessionBusyError,
    SessionCameraError,
    camera_session_manager,
)
from app.services.stream_protocol import encode_ws_message

router = APIRouter(tags=["stream"])

_FRAME_INTERVAL = 1.0 / TARGET_FPS


@router.websocket("/ws/stream")
async def stream_camera(
    websocket: WebSocket,
    camera_id: str = Query(
        default="0",
        description="Índice USB (0, 1, …), URL rtsp:// o ruta a archivo de video.",
    ),
) -> None:
    """
    Transmite frames de la cámara procesados en tiempo real.
    """
    await websocket.accept()

    settings = get_settings()
    client_id = str(uuid.uuid4())

    try:
        session = await camera_session_manager.acquire(camera_id, client_id)
    except SessionBusyError as exc:
        await websocket.send_json(
            {
                "connected": False,
                "camera_id": camera_id,
                "error": exc.code,
                "description": "La cámara ya está en uso por otro cliente. "
                "Intente de nuevo cuando se libere.",
            }
        )
        await websocket.close(code=1008)
        return
    except SessionCameraError as exc:
        await websocket.send_json(
            {
                "connected": False,
                "camera_id": camera_id,
                "error": exc.code,
                "description": str(exc),
            }
        )
        await websocket.close(code=1000)
        return

    try:
        await websocket.send_json(
            {
                "connected": True,
                "camera_id": camera_id,
                "error": None,
                "description": "Cámara detectada. Iniciando transmisión de video.",
            }
        )

        loop = asyncio.get_running_loop()

        while True:
            t0 = time.monotonic()

            frame = await loop.run_in_executor(None, session.capture.read_frame)
            session.update_frame(frame)

            if frame is None:
                session.record_error("La cámara dejó de enviar frames.")
                await websocket.send_json(
                    {
                        "connected": False,
                        "camera_id": camera_id,
                        "error": "CAMERA_NO_FRAMES",
                        "description": "La cámara dejó de enviar frames.",
                    }
                )
                await websocket.close(code=1000)
                break

            message = await loop.run_in_executor(
                None,
                lambda: encode_ws_message(
                    frame,
                    [],
                    session.metrics.fps_current,
                    camera_id,
                    settings.jpeg_quality,
                ),
            )
            await websocket.send_bytes(message)

            elapsed = time.monotonic() - t0
            sleep_for = max(0.0, _FRAME_INTERVAL - elapsed)
            if sleep_for:
                await asyncio.sleep(sleep_for)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        session.record_error(str(exc))
        # El socket puede estar ya cerrado
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
    finally:
        # Pase lo que pase, la cámara vuelve a quedar disponible.
        await camera_session_manager.release(client_id)
