"""
Ciclo de comunicación WebSocket del stream de cámara.

La captura vive en la sesión (CameraSessionManager) y publica en un FrameSlot.
Aquí solo se consume ese slot con tareas independientes:

  - emisor:     toma el frame más reciente, lo serializa y lo envía.
  - receptor:   escucha el socket para detectar la desconexión del cliente
                aunque el emisor esté bloqueado en un envío lento. Con `control`
                atiende además el mensaje `update_roi` (ver stream_control.py).
  - inferencia: (opcional) calcula detecciones sobre el frame más reciente
                sin frenar el video.

Cuando cualquiera termina, las demás se cancelan y se esperan antes de liberar
la sesión, de modo que la cámara se libera sin tareas pendientes.

Sincronía frame-detecciones (con inferencia): la inferencia deja de ser una tarea
aparte que publica "las últimas detecciones". Un único ciclo toma el frame más
reciente, lo infiere y envía JPEG y detecciones con el MISMO `seq`. Nunca se
reutilizan detecciones de otro frame: si no hubo inferencia válida para ese
frame, el mensaje lleva `detections: []` y un `detections_status` que explica por
qué. No hay cola: `slot.next` solo entrega el frame más reciente y a lo sumo hay
una inferencia en vuelo.

Ciclo de vida (M07): cada cliente consume el slot que recibió al conectarse.
Si un operador detiene la sesión, lo desconecta o el servicio se apaga, ese
slot se cierra con el código de la causa y aquí se traduce en el mensaje y el
código de cierre que recibe el cliente (ver CLOSE_CODES).
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
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
from app.services.redaction import redact_source, redact_text
from app.services.stream_control import RoiConfig, RoiOutOfFrame, StreamControl, roi_to_dict
from app.services.stream_protocol import encode_ws_message

logger = logging.getLogger(__name__)

# Sin `control`: infer(frame). Con `control`: infer(frame, roi), con roi = (x1, y1, x2, y2) | None.
InferFn = Callable[..., list]

# Tiempo máximo que un frame espera su inferencia antes de enviarse sin detecciones.
# Imagen y detecciones viajan juntas, así que un frame solo puede llevar detecciones
# si su inferencia termina dentro de este plazo; si no, el video sigue con el frame
# actual (una inferencia lenta no debe frenar el video). Con un modelo más lento que
# el plazo no se entregan detecciones: el cliente puede subirlo con `inference_timeout_s`.
INFERENCE_TIMEOUT_S = 0.1

# Valores de `detections_status` en cada mensaje
STATUS_OK = "ok"                # detecciones calculadas sobre ESTE frame
STATUS_SKIPPED = "skipped"      # este frame no tocaba inferir (infer_every_n_frames)
STATUS_TIMEOUT = "timeout"      # la inferencia de este frame no terminó a tiempo
STATUS_BUSY = "busy"            # sigue en curso una inferencia anterior
STATUS_ROI_OUT_OF_FRAME = "roi_out_of_frame"  # la ROI activa no cabe en este frame
STATUS_DISABLED = "disabled"    # el stream no tiene inferencia

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
    "CAMERA_STALLED": 1011,          # la cámara se estancó y no se pudo recuperar
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

        # Tamaño del frame ORIGINAL: las cajas se entregan en sus coordenadas.
        height, width = packet.frame.shape[:2]
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
            {"frame_width": width, "frame_height": height},
        )
        await websocket.send_bytes(message)
        session.delivery.frames_sent += 1


async def _receive_loop(
    websocket: WebSocket,
    control: Optional[StreamControl] = None,
    send_lock: Optional[asyncio.Lock] = None,
) -> None:
    """
    Escucha el socket. Detecta la desconexión y, si hay `control`, atiende los
    mensajes de texto (update_roi). Un mensaje inválido jamás cierra el socket.
    """
    send_lock = send_lock or asyncio.Lock()
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        text = message.get("text")
        if control is None or text is None:
            continue
        reply = control.handle_text(text)
        async with send_lock:
            await websocket.send_json(reply)


def _call_infer(infer: InferFn, frame: np.ndarray, roi, with_roi: bool) -> tuple:
    """Se ejecuta en un hilo. Una ROI fuera del frame no es un fallo del stream."""
    try:
        return (infer(frame, roi) if with_roi else infer(frame)), STATUS_OK
    except RoiOutOfFrame:
        return [], STATUS_ROI_OUT_OF_FRAME


def _log_late_failure(future: asyncio.Future) -> None:
    """Consume el resultado de una inferencia que ya nadie espera (timeout/cancelación)."""
    if future.cancelled():
        return
    error = future.exception()
    if error is not None:
        logger.warning("Una inferencia descartada terminó con error: %s", error)


async def _pipeline_loop(
    websocket: WebSocket,
    session: CameraSession,
    slot: FrameSlot,
    camera_id: str,
    jpeg_quality: int,
    infer: Optional[InferFn],
    every_n_frames: int,
    timeout_s: float,
    control: Optional[StreamControl] = None,
    send_lock: Optional[asyncio.Lock] = None,
) -> None:
    loop = asyncio.get_running_loop()
    send_lock = send_lock or asyncio.Lock()
    last_seq = 0
    last_inferred_seq = 0
    inflight: Optional[asyncio.Future] = None

    while True:
        # Solo el frame más reciente: lo que se acumule mientras se infiere se omite.
        packet = await slot.next(last_seq)
        if last_seq:
            session.delivery.frames_skipped += packet.seq - last_seq - 1
        last_seq = packet.seq

        frame = packet.frame
        height, width = frame.shape[:2]
        if control is not None:
            control.set_frame_size(width, height)
            config = control.config  # instantánea: la ROI de este frame no cambia a medias
        else:
            config = RoiConfig()

        detections: list = []
        status = STATUS_DISABLED
        if infer is not None:
            status = STATUS_SKIPPED
            due = last_inferred_seq == 0 or packet.seq - last_inferred_seq >= every_n_frames
            if due:
                if inflight is not None and not inflight.done():
                    status = STATUS_BUSY
                else:
                    last_inferred_seq = packet.seq
                    inflight = loop.run_in_executor(
                        None, _call_infer, infer, frame, config.roi, control is not None
                    )
                    inflight.add_done_callback(_log_late_failure)
                    try:
                        detections, status = await asyncio.wait_for(
                            asyncio.shield(inflight), timeout_s
                        )
                    except asyncio.TimeoutError:
                        detections, status = [], STATUS_TIMEOUT

        extra = {
            "captured_at": packet.captured_at,
            "frame_width": width,
            "frame_height": height,
            "detections_status": status,
        }
        if control is not None:
            # Con qué ROI/versión se infirió ESTE frame
            extra["roi"] = roi_to_dict(config.roi)
            extra["roi_version"] = config.version
        message = await loop.run_in_executor(
            None,
            functools.partial(
                encode_ws_message,
                frame,
                detections,
                session.metrics.fps_current,
                camera_id,
                jpeg_quality,
                packet.seq,
                packet.captured_at,
                extra,
            ),
        )
        async with send_lock:
            await websocket.send_bytes(message)
        session.delivery.frames_sent += 1


async def _run_tasks(
    websocket: WebSocket,
    session: CameraSession,
    slot: FrameSlot,
    camera_id: str,
    infer: Optional[InferFn],
    infer_every_n_frames: int,
    inference_timeout_s: float = INFERENCE_TIMEOUT_S,
    control: Optional[StreamControl] = None,
) -> None:
    settings = get_settings()
    send_lock = asyncio.Lock()  # el receptor responde y el emisor envía por el mismo socket

    if infer is not None or control is not None:
        # Con inferencia o con control: un solo ciclo envía cada frame con sus propias detecciones.
        receiver = asyncio.create_task(_receive_loop(websocket, control, send_lock))
        tasks = [
            receiver,
            asyncio.create_task(
                _pipeline_loop(
                    websocket,
                    session,
                    slot,
                    camera_id,
                    settings.jpeg_quality,
                    infer,
                    infer_every_n_frames,
                    inference_timeout_s,
                    control,
                    send_lock,
                )
            ),
        ]
    else:
        detections = _Detections()
        receiver = asyncio.create_task(_receive_loop(websocket))
        tasks = [
            receiver,
            asyncio.create_task(
                _send_loop(websocket, session, slot, camera_id, settings.jpeg_quality, detections)
            ),
        ]

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
        await _notify_and_close(
            websocket, camera_id, error.code, redact_text(str(error)), close_code
        )
        return
    session.record_error(str(error))
    await _notify_and_close(
        websocket, camera_id, STREAM_ERROR_CODE, redact_text(str(error)), 1011
    )


async def serve_camera_stream(
    websocket: WebSocket,
    manager: CameraSessionManager,
    camera_id: str,
    ready_description: str,
    infer: Optional[InferFn] = None,
    infer_every_n_frames: int = 1,
    inference_timeout_s: float = INFERENCE_TIMEOUT_S,
    control: Optional[StreamControl] = None,
) -> None:
    """
    Atiende un cliente WebSocket de principio a fin.

    Con `infer`, cada mensaje lleva imagen y detecciones del mismo frame (ver
    el docstring del módulo). Sin `infer` se transmite solo el video.

    Con `control` (ROI en vivo) el cliente puede enviar `update_roi`, `infer` se
    llama como `infer(frame, roi)` y cada mensaje informa la ROI usada.

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

    # La cámara se abre con la fuente real; al cliente solo le llega la versión
    # sin credenciales (M12).
    public_id = redact_source(camera_id)

    try:
        session = await manager.acquire(camera_id, client_id)
    except SessionError as exc:
        description = (
            _BUSY_DESCRIPTION if exc.code == "CAMERA_BUSY" else redact_text(str(exc), camera_id)
        )
        await _notify_and_close(
            websocket, public_id, exc.code, description, CLOSE_CODES.get(exc.code, 1011)
        )
        return

    # El slot de esta conexión: si la sesión sigue después de que este cliente
    # se vaya, el siguiente cliente recibirá uno nuevo.
    slot = session.frames

    try:
        await websocket.send_json(
            {
                "connected": True,
                "camera_id": public_id,
                "client_id": client_id,
                "state": manager.state.value,
                "started_by": session.started_by.value,
                "error": None,
                "description": ready_description,
            }
        )
        if control is not None and control.startup_notice is not None:
            await websocket.send_json(control.startup_notice)
        await _run_tasks(
            websocket,
            session,
            slot,
            public_id,
            infer,
            infer_every_n_frames,
            inference_timeout_s,
            control,
        )
    except WebSocketDisconnect:
        pass
    finally:
        # Pase lo que pase, la cámara vuelve a quedar disponible.
        await manager.release(client_id)
