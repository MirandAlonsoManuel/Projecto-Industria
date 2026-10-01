"""
Ciclo de comunicación WebSocket del stream de cámara.

La captura vive en la sesión (CameraSessionManager) y publica en un FrameSlot.
Aquí solo se consume ese slot con tareas independientes:

  - emisor:     toma el frame más reciente, lo serializa y lo envía.
  - receptor:   escucha el socket para detectar la desconexión del cliente
                aunque el emisor esté bloqueado en un envío lento.
  - inferencia: (opcional) calcula detecciones sobre el frame más reciente
                sin frenar el video.

Cuando cualquiera termina, las demás se cancelan y se esperan antes de liberar
la sesión, de modo que la cámara se libera sin tareas pendientes.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.services.camera_session_manager import (
    NO_FRAMES_CODE,
    CameraSession,
    CameraSessionManager,
    SessionBusyError,
    SessionCameraError,
)
from app.services.frame_slot import FrameSlotClosed
from app.services.stream_protocol import encode_ws_message

InferFn = Callable[[np.ndarray], list]

STREAM_ERROR_CODE = "STREAM_ERROR"


@dataclass
class _Detections:
    items: list = field(default_factory=list)


async def _notify_and_close(
    websocket: WebSocket, camera_id: str, error: str, description: str, code: int
) -> None:
    """Informa el motivo al cliente y cierra; tolera un socket ya cerrado."""
    with contextlib.suppress(RuntimeError, WebSocketDisconnect, OSError):
        await websocket.send_json(
            {
                "connected": False,
                "camera_id": camera_id,
                "error": error,
                "description": description,
            }
        )
        await websocket.close(code=code)


async def _send_loop(
    websocket: WebSocket,
    session: CameraSession,
    camera_id: str,
    jpeg_quality: int,
    detections: _Detections,
) -> None:
    loop = asyncio.get_running_loop()
    last_seq = 0
    while True:
        packet = await session.frames.next(last_seq)
        if last_seq:
            session.delivery.frames_skipped += packet.seq - last_seq - 1
        last_seq = packet.seq

        message = await loop.run_in_executor(
            None,
            encode_ws_message,
            packet.frame,
            detections.items,
            session.metrics.fps_current,
            camera_id,
            jpeg_quality,
            packet.seq,
            packet.captured_at,
        )
        await websocket.send_bytes(message)
        session.delivery.frames_sent += 1


async def _receive_loop(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def _inference_loop(
    session: CameraSession,
    infer: InferFn,
    every_n_frames: int,
    detections: _Detections,
) -> None:
    loop = asyncio.get_running_loop()
    last_seq = 0
    while True:
        # Primer frame disponible y luego uno cada N; si la inferencia tardó
        # más que eso, se toma directamente el más reciente.
        after = last_seq + every_n_frames - 1 if last_seq else 0
        packet = await session.frames.next(after)
        detections.items = await loop.run_in_executor(None, infer, packet.frame)
        last_seq = packet.seq


async def _run_tasks(
    websocket: WebSocket,
    session: CameraSession,
    camera_id: str,
    infer: Optional[InferFn],
    infer_every_n_frames: int,
) -> None:
    settings = get_settings()
    detections = _Detections()

    receiver = asyncio.create_task(_receive_loop(websocket))
    tasks = [
        receiver,
        asyncio.create_task(
            _send_loop(websocket, session, camera_id, settings.jpeg_quality, detections)
        ),
    ]
    if infer is not None:
        tasks.append(
            asyncio.create_task(
                _inference_loop(session, infer, infer_every_n_frames, detections)
            )
        )

    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if receiver in done:
        return  # el cliente se desconectó

    error = next(
        (t.exception() for t in done if not t.cancelled() and t.exception() is not None),
        None,
    )
    if error is None or isinstance(error, WebSocketDisconnect):
        return
    if isinstance(error, FrameSlotClosed):
        close_code = 1000 if error.code == NO_FRAMES_CODE else 1011
        await _notify_and_close(websocket, camera_id, error.code, str(error), close_code)
        return
    session.record_error(str(error))
    await _notify_and_close(websocket, camera_id, STREAM_ERROR_CODE, str(error), 1011)


async def serve_camera_stream(
    websocket: WebSocket,
    manager: CameraSessionManager,
    camera_id: str,
    ready_description: str,
    infer: Optional[InferFn] = None,
    infer_every_n_frames: int = 1,
) -> None:
    """
    Atiende un cliente WebSocket de principio a fin.

    Códigos de cierre:
    - 1000 — cierre normal (sin cámara, cámara sin frames o cliente desconectado).
    - 1008 — sesión ocupada: ya hay un cliente activo.
    - 1011 — error interno del servidor.
    """
    await websocket.accept()
    client_id = str(uuid.uuid4())

    try:
        session = await manager.acquire(camera_id, client_id)
    except SessionBusyError as exc:
        await _notify_and_close(
            websocket,
            camera_id,
            exc.code,
            "La cámara ya está en uso por otro cliente. "
            "Intente de nuevo cuando se libere.",
            1008,
        )
        return
    except SessionCameraError as exc:
        await _notify_and_close(websocket, camera_id, exc.code, str(exc), 1000)
        return

    try:
        await websocket.send_json(
            {
                "connected": True,
                "camera_id": camera_id,
                "error": None,
                "description": ready_description,
            }
        )
        await _run_tasks(websocket, session, camera_id, infer, infer_every_n_frames)
    except WebSocketDisconnect:
        pass
    finally:
        # Pase lo que pase, la cámara vuelve a quedar disponible.
        await manager.release(client_id)
