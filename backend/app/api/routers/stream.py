"""
Router WebSocket para streaming en tiempo real de frames de cámara.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket

from app.services.camera_session_manager import camera_session_manager
from app.services.stream_runner import serve_camera_stream

router = APIRouter(tags=["stream"])


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
    await serve_camera_stream(
        websocket,
        camera_session_manager,
        camera_id,
        "Cámara detectada. Iniciando transmisión de video.",
    )
