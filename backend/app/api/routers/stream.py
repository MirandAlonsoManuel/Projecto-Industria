"""
Router WebSocket para streaming en tiempo real de frames de cámara.

Protocolo binario por mensaje:
  [4 bytes uint32 big-endian = longitud JSON] [JSON metadata UTF-8] [JPEG bytes]

El primer mensaje siempre es JSON de texto con el estado de conexión. El ciclo
de vida (conexión, rechazos, fin de sesión y cierre) lo resuelve
`app.api.ws_camera.run_camera_stream`, compartido con `/ws/inference-stream`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, WebSocket

from app.api.ws_camera import run_camera_stream
from app.core.config import get_settings
from app.services.camera_service import encode_ws_message
from app.services.camera_session_manager import camera_session_manager

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
    Transmite frames de la cámara en tiempo real.

    Si no hay sesión iniciada, la conexión la inicia y al desconectarse la
    cierra. Si un operador la inició antes, la cámara sigue abierta al salir.

    Códigos de cierre WebSocket:
    - 1000 — cierre normal: desconexión limpia, sesión detenida, sin cámara o sin frames.
    - 1001 — el servicio se está apagando.
    - 1008 — rechazo por política: cámara ocupada o cámara distinta a la de la sesión.
    - 1011 — error interno o de procesamiento.
    """
    settings = get_settings()
    loop = asyncio.get_running_loop()

    async def on_frame(frame, session, frame_index: int) -> bytes:
        return await loop.run_in_executor(
            None,
            lambda: encode_ws_message(
                frame,
                [],
                session.metrics.fps_current,
                camera_id,
                settings.jpeg_quality,
            ),
        )

    await run_camera_stream(
        websocket,
        camera_session_manager,
        camera_id,
        on_frame,
        welcome="Cámara detectada. Iniciando transmisión de video.",
    )
