"""
Flujo compartido de los WebSocket de cámara (M07).

`/ws/stream` y `/ws/inference-stream` atraviesan el mismo ciclo de vida:
conectar al único cliente, transmitir mientras la sesión siga activa y
desconectarlo siempre al final. Solo cambia lo que cada uno hace con el frame,
que llega como la función `on_frame`. Así ambos responden con los mismos
mensajes, códigos de error y códigos de cierre.

Mensaje de conexión aceptada:
  {"connected": true, "camera_id", "client_id", "state", "started_by",
   "error": null, "description"}

Mensaje de fin o rechazo (siempre antes del cierre):
  {"connected": false, "camera_id", "error": <código>, "description"}
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Awaitable, Callable, Optional

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from app.core.limits import TARGET_FPS
from app.services.camera_session_manager import (
    CameraSession,
    CameraSessionManager,
    ClientSessionEndedError,
    SessionError,
)

FrameHandler = Callable[[np.ndarray, CameraSession, int], Awaitable[bytes]]

_FRAME_INTERVAL = 1.0 / TARGET_FPS

# Código de cierre WebSocket para cada causa de fin o rechazo
CLOSE_CODES: dict[str, int] = {
    "CAMERA_BUSY": 1008,             # política: ya hay un cliente activo
    "CAMERA_MISMATCH": 1008,         # política: la sesión usa otra cámara
    "CAMERA_UNAVAILABLE": 1000,
    "CAMERA_NO_FRAMES": 1000,
    "SESSION_STOPPED": 1000,         # un operador detuvo la sesión
    "CLIENT_DISCONNECTED": 1000,     # un operador desconectó al cliente
    "SERVICE_SHUTTING_DOWN": 1001,   # el servidor se está apagando
    "SERVICE_SHUTDOWN": 1001,
    "PROCESSING_ERROR": 1011,        # falló el procesamiento del frame
}

DESCRIPTIONS: dict[str, str] = {
    "SESSION_STOPPED": "La sesión de cámara fue detenida.",
    "CLIENT_DISCONNECTED": "Un operador cerró esta conexión.",
    "SERVICE_SHUTDOWN": "El servicio se está apagando.",
    "CAMERA_NO_FRAMES": "La cámara dejó de enviar frames.",
}


async def _end(
    websocket: WebSocket, camera_id: str, code: str, description: Optional[str] = None
) -> None:
    """Explica al cliente por qué termina la conexión y la cierra.

    Si el cliente ya se fue, enviar falla; eso no debe interrumpir la limpieza.
    """
    with contextlib.suppress(Exception):
        await websocket.send_json(
            {
                "connected": False,
                "camera_id": camera_id,
                "error": code,
                "description": description or DESCRIPTIONS.get(code, code),
            }
        )
    with contextlib.suppress(Exception):
        await websocket.close(code=CLOSE_CODES.get(code, 1011))


async def run_camera_stream(
    websocket: WebSocket,
    manager: CameraSessionManager,
    camera_id: str,
    on_frame: FrameHandler,
    *,
    welcome: str = "Cámara detectada. Iniciando transmisión de video.",
) -> None:
    """Atiende a un cliente WebSocket durante todo su ciclo de vida."""
    await websocket.accept()
    client_id = str(uuid.uuid4())

    try:
        session = await manager.connect_client(camera_id, client_id)
    except SessionError as exc:
        await _end(websocket, camera_id, exc.code, str(exc))
        return

    try:
        await websocket.send_json(
            {
                "connected": True,
                "camera_id": camera_id,
                "client_id": client_id,
                "state": manager.state.value,
                "started_by": session.started_by.value,
                "error": None,
                "description": welcome,
            }
        )

        frame_index = 0
        while True:
            t0 = time.monotonic()

            try:
                frame = await manager.read_frame(client_id)
            except ClientSessionEndedError as exc:
                await _end(websocket, camera_id, exc.code)
                break

            if frame is None:
                session.record_error(DESCRIPTIONS["CAMERA_NO_FRAMES"])
                await _end(websocket, camera_id, "CAMERA_NO_FRAMES")
                break

            try:
                message = await on_frame(frame, session, frame_index)
            except Exception as exc:
                session.record_error(str(exc))
                await _end(websocket, camera_id, "PROCESSING_ERROR", str(exc))
                break

            await websocket.send_bytes(message)
            frame_index += 1

            sleep_for = _FRAME_INTERVAL - (time.monotonic() - t0)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        session.record_error(str(exc))
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
    finally:
        # Pase lo que pase, el cliente sale del ciclo de vida
        await manager.disconnect_client(client_id)
