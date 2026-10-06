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

Ciclo de vida (M07): cada cliente consume el slot que recibió al conectarse.
Si un operador detiene la sesión, lo desconecta o el servicio se apaga, ese
slot se cierra con el código de la causa y aquí se traduce en el mensaje y el
código de cierre que recibe el cliente (ver CLOSE_CODES).
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
    CameraSession,
    CameraSessionManager,
    SessionError,
)
from app.services.frame_slot import FrameSlot, FrameSlotClosed
from app.services.stream_protocol import encode_ws_message

InferFn = Callable[[np.ndarray], list]

STREAM_ERROR_CODE = "STREAM_ERROR"

# Código de cierre WebSocket para cada causa de rechazo o de fin de sesión
CLOSE_CODES: dict[str, int] = {
    "CAMERA_BUSY": 1008,             # política: ya hay un cliente activo
    "CAMERA_MISMATCH": 1008,         # política: la sesión usa otra cámara
    "CAMERA_UNAVAILABLE": 1000,
    "CAMERA_NO_FRAMES": 1000,
    "STREAM_CLOSED": 1000,
    "SESSION_STOPPED": 1000,         # un operador detuvo la sesión
    "CLIENT_DISCONNECTED": 1000,     # un operador desconectó al cliente
    "SERVICE_SHUTTING_DOWN": 1001,   # el servidor se está apagando
    "SERVICE_SHUTDOWN": 1001,
    "CAMERA_READ_ERROR": 1011,
    STREAM_ERROR_CODE: 1011,
}

_BUSY_DESCRIPTION = (
    "La cámara ya está en uso por otro cliente. Intente de nuevo cuando se libere."
)


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
    slot: FrameSlot,
    camera_id: str,
    jpeg_quality: int,
    detections: _Detections,
) -> None:
    loop = asyncio.get_running_loop()
    last_seq = 0
    while True:
        packet = await slot.next(last_seq)
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
    slot: FrameSlot,
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
        packet = await slot.next(after)
        detections.items = await loop.run_in_executor(None, infer, packet.frame)
        last_seq = packet.seq


async def _run_tasks(
    websocket: WebSocket,
    session: CameraSession,
    slot: FrameSlot,
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
            _send_loop(websocket, session, slot, camera_id, settings.jpeg_quality, detections)
        ),
    ]
    if infer is not None:
        tasks.append(
            asyncio.create_task(
                _inference_loop(slot, infer, infer_every_n_frames, detections)
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
        close_code = CLOSE_CODES.get(error.code, 1011)
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

    Si no hay sesión iniciada, la conexión la inicia y al desconectarse la
    cierra. Si un operador la inició antes, la cámara sigue abierta al salir.

    Códigos de cierre:
    - 1000 — cierre normal: cliente desconectado, sesión detenida o expulsión
             por operador, sin cámara o cámara sin frames.
    - 1001 — el servicio se está apagando.
    - 1008 — rechazo por política: cámara ocupada o cámara distinta a la de la sesión.
    - 1011 — error interno, de lectura o de procesamiento.
    """
    await websocket.accept()
    client_id = str(uuid.uuid4())

    try:
        session = await manager.acquire(camera_id, client_id)
    except SessionError as exc:
        description = _BUSY_DESCRIPTION if exc.code == "CAMERA_BUSY" else str(exc)
        await _notify_and_close(
            websocket, camera_id, exc.code, description, CLOSE_CODES.get(exc.code, 1011)
        )
        return

    # El slot de esta conexión: si la sesión sigue después de que este cliente
    # se vaya, el siguiente cliente recibirá uno nuevo.
    slot = session.frames

    try:
        await websocket.send_json(
            {
                "connected": True,
                "camera_id": camera_id,
                "client_id": client_id,
                "state": manager.state.value,
                "started_by": session.started_by.value,
                "error": None,
                "description": ready_description,
            }
        )
        await _run_tasks(websocket, session, slot, camera_id, infer, infer_every_n_frames)
    except WebSocketDisconnect:
        pass
    finally:
        # Pase lo que pase, la cámara vuelve a quedar disponible.
        await manager.release(client_id)
