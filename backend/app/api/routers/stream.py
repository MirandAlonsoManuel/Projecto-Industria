"""
Router WebSocket para streaming en tiempo real de frames de cámara.

Protocolo binario por mensaje:
  [4 bytes uint32 big-endian = longitud JSON] [JSON metadata UTF-8] [JPEG bytes]

El primer mensaje siempre es JSON de texto con el estado de conexión.

Política de acceso: **un solo cliente por cámara**. Si `camera_id` ya tiene
una sesión activa (in_use o reconnecting), la nueva conexión se rechaza sin
tocar el hardware.

Ante una falla de lectura, la sesión intenta reconectar con backoff en vez
de cerrar la conexión de inmediato; el cliente recibe mensajes de estado
mientras dura el intento. Solo se cierra el WebSocket si se agotan los
reintentos configurados.

Test del websocket con ws://127.0.0.1:8000/ws/stream?camera_id=0
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.services.camera_registry import (
    CameraBusyError,
    CameraSlot,
    CameraState,
    get_camera_registry,
)
from app.services.camera_service import encode_ws_message

router = APIRouter(tags=["stream"])

_TARGET_FPS = 30
_FRAME_INTERVAL = 1.0 / _TARGET_FPS

# [SUPUESTO] Código de cierre para "cámara ya en uso por otro cliente".
# Se usa el 1013 estándar (Try Again Later) mientras el líder técnico no
# defina un esquema de errores propio de la aplicación para WebSocket.
_WS_CODE_CAMERA_BUSY = 1013


class _FPSTracker:
    """Calcula FPS promedio sobre una ventana deslizante de frames."""

    def __init__(self, window: int = 30) -> None:
        self._times: deque[float] = deque(maxlen=window)

    def tick(self) -> float:
        self._times.append(time.monotonic())
        if len(self._times) < 2:
            return 0.0
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])


def _describe_state(slot: CameraSlot) -> str:
    if slot.state == CameraState.RECONNECTING:
        return (
            f"Intentando reconectar con la cámara "
            f"(intento {slot.retry_count})..."
        )
    if slot.state == CameraState.IN_USE:
        return "Cámara detectada. Transmisión de video activa."
    return slot.last_error or "Estado desconocido."


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

    **Flujo de mensajes:**
    1. El servidor envía un mensaje **JSON texto** con el estado de conexión.
    2. Si `connected` es `true`, los mensajes siguientes son **binarios**
       (header 4B + JSON + JPEG), salvo mensajes de estado intercalados
       durante una reconexión.
    3. Si la cámara falla, se envía un JSON con `state: "reconnecting"` y
       la conexión **permanece abierta** mientras se reintenta.
    4. Solo si se agotan los reintentos se envía `connected: false` y se
       cierra la conexión.

    **Códigos de cierre WebSocket:**
    - `1000` — cierre normal (sin cámara, reintentos agotados, o
      desconexión limpia del cliente).
    - `1013` — la cámara ya tiene otro cliente conectado.
    - `1011` — error interno del servidor.
    """
    await websocket.accept()  # HTTP 101 Switching Protocols

    settings = get_settings()
    registry = get_camera_registry()

    try:
        slot = await registry.acquire(camera_id)
    except CameraBusyError:
        await websocket.send_json(
            {
                "connected": False,
                "camera_id": camera_id,
                "state": CameraState.IN_USE.value,
                "description": (
                    f"La cámara '{camera_id}' ya tiene un cliente conectado. "
                    "Solo se permite una conexión activa por cámara."
                ),
            }
        )
        await websocket.close(code=_WS_CODE_CAMERA_BUSY)
        return
    except ConnectionError:
        await websocket.send_json(
            {
                "connected": False,
                "camera_id": camera_id,
                "state": CameraState.OFFLINE.value,
                "description": (
                    f"No se detectó ninguna cámara en el dispositivo "
                    f"(fuente: '{camera_id}'). "
                    "Verifique que la cámara esté conectada y no esté "
                    "siendo usada por otra aplicación."
                ),
            }
        )
        await websocket.close(code=1000)
        return

    async def notify_state(current_slot: CameraSlot) -> None:
        await websocket.send_json(
            {
                "connected": True,
                "camera_id": camera_id,
                "state": current_slot.state.value,
                "retry_count": current_slot.retry_count,
                "description": _describe_state(current_slot),
            }
        )

    try:
        await websocket.send_json(
            {
                "connected": True,
                "camera_id": camera_id,
                "state": CameraState.IN_USE.value,
                "description": "Cámara detectada. Iniciando transmisión de video.",
            }
        )

        fps_tracker = _FPSTracker()

        while True:
            t0 = time.monotonic()

            frame = await registry.read_frame_with_reconnect(
                slot, on_state_change=notify_state
            )

            if frame is None:
                # Se agotaron los reintentos; el registro ya liberó la sesión.
                await websocket.send_json(
                    {
                        "connected": False,
                        "camera_id": camera_id,
                        "state": CameraState.OFFLINE.value,
                        "description": slot.last_error
                        or "La cámara dejó de responder.",
                    }
                )
                await websocket.close(code=1000)
                return

            fps = fps_tracker.tick()

            message = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: encode_ws_message(
                    frame,
                    [],  # detecciones — el pipeline ML las inyecta en producción
                    fps,
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
    except Exception:
        await websocket.close(code=1011)
    finally:
        # Idempotente: si ya se liberó por agotar reintentos, no hace nada.
        await registry.release(camera_id)
