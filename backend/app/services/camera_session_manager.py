
from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import numpy as np

from app.core.limits import (
    FPS_WINDOW_FRAMES,
    FRAME_STALE_TIMEOUT_S,
    MAX_ERROR_HISTORY,
    TARGET_FPS,
)
from app.services.camera_service import CameraCapture, open_camera
from app.services.frame_slot import FrameSlot

logger = logging.getLogger(__name__)

NO_FRAMES_CODE = "CAMERA_NO_FRAMES"
_NO_FRAMES_MESSAGE = "La cámara dejó de enviar frames."


# ── Estado ────────────────────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    IDLE = "idle"
    STREAMING = "streaming"
    ERROR = "error"


# ── Estructuras de datos ──────────────────────────────────────────────────────

@dataclass
class ErrorRecord:
    timestamp: float
    message: str


@dataclass
class SessionMetrics:
    frames_total: int = 0
    frames_dropped: int = 0
    fps_current: float = 0.0
    started_at: Optional[float] = None
    _fps_times: deque = field(
        default_factory=lambda: deque(maxlen=FPS_WINDOW_FRAMES),
        repr=False,
    )

    @property
    def uptime_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        return time.monotonic() - self.started_at

    def tick_frame(self) -> None:
        now = time.perf_counter()
        self._fps_times.append(now)
        self.frames_total += 1
        if len(self._fps_times) >= 2:
            elapsed = self._fps_times[-1] - self._fps_times[0]
            if elapsed > 0:
                self.fps_current = (len(self._fps_times) - 1) / elapsed

    def tick_drop(self) -> None:
        self.frames_dropped += 1

    def to_dict(self) -> dict:
        return {
            "frames_total": self.frames_total,
            "frames_dropped": self.frames_dropped,
            "fps_current": round(self.fps_current, 2),
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


@dataclass
class DeliveryMetrics:
    """Entrega al cliente: frames enviados y frames que se saltó por ir lento."""

    frames_sent: int = 0
    frames_skipped: int = 0

    def to_dict(self) -> dict:
        return {
            "frames_sent": self.frames_sent,
            "frames_skipped": self.frames_skipped,
        }


@dataclass
class CameraSession:
    camera_id: str
    capture: CameraCapture
    status: SessionStatus = SessionStatus.STREAMING
    active_client: Optional[str] = None
    last_frame: Optional[np.ndarray] = None
    last_frame_ts: float = 0.0
    metrics: SessionMetrics = field(default_factory=SessionMetrics)
    delivery: DeliveryMetrics = field(default_factory=DeliveryMetrics)
    errors: deque = field(
        default_factory=lambda: deque(maxlen=MAX_ERROR_HISTORY),
        repr=False,
    )
    frames: FrameSlot = field(default_factory=FrameSlot, repr=False)
    capture_task: Optional[asyncio.Task] = field(default=None, repr=False)

    def update_frame(self, frame: Optional[np.ndarray]) -> None:
        """Actualiza el último frame y avanza las métricas."""
        if frame is None:
            self.metrics.tick_drop()
            return
        self.last_frame = frame
        self.last_frame_ts = time.time()
        self.metrics.tick_frame()

    def record_error(self, message: str) -> None:
        """Registra un error y transiciona el estado a ERROR."""
        self.errors.append(ErrorRecord(timestamp=time.time(), message=message))
        self.status = SessionStatus.ERROR

    def to_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "status": self.status.value,
            "active_client": self.active_client,
            "last_frame_ts": self.last_frame_ts or None,
            "metrics": self.metrics.to_dict(),
            "delivery": self.delivery.to_dict(),
            "errors": [
                {"timestamp": e.timestamp, "message": e.message}
                for e in self.errors
            ],
        }


# ── Excepciones ───────────────────────────────────────────────────────────────

class SessionBusyError(RuntimeError):
    """La sesión ya tiene un cliente activo."""

    code = "CAMERA_BUSY"


class SessionCameraError(RuntimeError):
    """No se pudo abrir la fuente de cámara solicitada."""

    code = "CAMERA_UNAVAILABLE"


# ── Utilidades internas ───────────────────────────────────────────────────────

def _release_quietly(capture: CameraCapture) -> None:
    """Cierra la captura sin propagar errores del driver.

    Un fallo al cerrar no debe dejar la sesión marcada como ocupada: se registra
    en el log y el gestor continúa como si el recurso hubiera quedado libre.
    """
    try:
        capture.release()
    except Exception:
        logger.exception("Error del driver al liberar la cámara; se da por liberada")


def _cleanup_orphan(future: asyncio.Future, cleanup: Callable[[Any], None]) -> None:
    """Aplica `cleanup` al resultado de una operación cuyo solicitante se canceló."""
    if future.cancelled() or future.exception() is not None:
        return
    result = future.result()
    if result is not None:
        cleanup(result)


# ── Captura ───────────────────────────────────────────────────────────────────

async def _capture_loop(session: CameraSession) -> None:
    """
    Ciclo de adquisición: lee la cámara a su ritmo y publica en el slot.

    No conoce al cliente ni al WebSocket. Termina si la cámara deja de
    entregar frames o si la tarea se cancela al liberar la sesión.
    """
    loop = asyncio.get_running_loop()
    interval = 1.0 / TARGET_FPS
    try:
        while True:
            t0 = time.monotonic()

            read = loop.run_in_executor(None, session.capture.read_frame)
            try:
                frame = await asyncio.shield(read)
            except asyncio.CancelledError:
                # La lectura sigue en su hilo: se espera a que termine para
                # que la cámara no se libere a mitad de un read.
                await asyncio.wait([read], timeout=FRAME_STALE_TIMEOUT_S)
                raise

            session.update_frame(frame)
            if frame is None:
                session.record_error(_NO_FRAMES_MESSAGE)
                session.frames.close(_NO_FRAMES_MESSAGE, code=NO_FRAMES_CODE)
                return
            session.frames.publish(frame, session.last_frame_ts)

            sleep_for = interval - (time.monotonic() - t0)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Error del driver al leer la cámara '%s'", session.camera_id)
        session.record_error(str(exc))
        session.frames.close(str(exc), code="CAMERA_READ_ERROR")


async def _stop_capture(session: CameraSession) -> None:
    """Cancela la tarea de captura y espera a que termine. No propaga errores."""
    task = session.capture_task
    session.capture_task = None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    session.frames.close("Sesión de cámara liberada.")


# ── Gestor ────────────────────────────────────────────────────────────────────

class CameraSessionManager:
    """
    Singleton que gestiona la única sesión activa de cámara.

    Un segundo cliente que llame a acquire() mientras la sesión está ocupada
    recibe SessionBusyError inmediatamente, sin bloquear ni abrir hardware.
    """

    def __init__(self) -> None:
        self._session: Optional[CameraSession] = None
        self._lock = asyncio.Lock()

    @property
    def session(self) -> Optional[CameraSession]:
        return self._session

    @property
    def is_busy(self) -> bool:
        return self._session is not None

    async def _run_blocking(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_orphan: Optional[Callable[[Any], None]] = None,
    ) -> Any:
    
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, fn, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if on_orphan is not None:
                future.add_done_callback(
                    functools.partial(_cleanup_orphan, cleanup=on_orphan)
                )
            try:
                await asyncio.wait({future})
            except asyncio.CancelledError:
                pass
            raise

    async def acquire(self, camera_id: str, client_id: str) -> CameraSession:
        """
        Reserva la sesión para el cliente dado.
        """
        async with self._lock:
            if self._session is not None:
                raise SessionBusyError(
                    f"Sesión ocupada por el cliente '{self._session.active_client}'. "
                    "Solo se permite un cliente activo a la vez."
                )

            try:
                capture = await self._run_blocking(
                    open_camera, camera_id, on_orphan=_release_quietly
                )
            except Exception as exc:
                raise SessionCameraError(
                    f"Error del driver al abrir la cámara '{camera_id}': {exc}"
                ) from exc

            if capture is None:
                raise SessionCameraError(
                    f"No se pudo abrir la cámara '{camera_id}'. "
                    "Verifique que esté conectada y no esté en uso."
                )

            self._session = CameraSession(
                camera_id=camera_id,
                capture=capture,
                active_client=client_id,
                metrics=SessionMetrics(started_at=time.monotonic()),
            )
            self._session.capture_task = asyncio.create_task(
                _capture_loop(self._session)
            )
            logger.info("Cámara '%s' asignada al cliente %s", camera_id, client_id)
            return self._session

    async def release(self, client_id: str) -> bool:
    
        async with self._lock:
            session = self._session
            if session is None or session.active_client != client_id:
                return False
            # La sesión se marca libre antes de cerrar: aunque el driver falle,
            # el recurso no queda secuestrado. El candado sigue tomado hasta que
            # el cierre termina, así nadie abre mientras aún se está cerrando.
            self._session = None
            # Primero se detiene la captura; la cámara se cierra después, aun
            # si esta liberación se cancela mientras espera a la tarea.
            try:
                await _stop_capture(session)
            finally:
                await self._run_blocking(_release_quietly, session.capture)
            logger.info("Cámara '%s' liberada por %s", session.camera_id, client_id)
            return True

    async def shutdown(self) -> None:
        """Libera cualquier sesión activa. Pensado para el apagado de FastAPI."""
        async with self._lock:
            session = self._session
            self._session = None
            if session is not None:
                try:
                    await _stop_capture(session)
                finally:
                    await self._run_blocking(_release_quietly, session.capture)

    async def scan_cameras(
        self, detector: Callable[..., list[dict]]
    ) -> list[dict]:
        """
        Escanea cámaras sin abrir nunca la que está en uso.
        """
        async with self._lock:
            active_id = self._session.camera_id if self._session else None
            exclude = {active_id} if active_id else set()
            cameras = await self._run_blocking(
                functools.partial(detector, exclude=exclude)
            )

        if active_id is not None and active_id.isdigit():
            cameras.append(
                {
                    "id": active_id,
                    "type": "usb",
                    "source_url": active_id,
                    "status": "in_use",
                }
            )
            cameras.sort(key=lambda cam: int(cam["id"]))
        return cameras

    def get_status(self) -> dict:
        """Estado serializable de la sesión actual."""
        if self._session is None:
            return {"status": SessionStatus.IDLE.value, "active_client": None}
        return self._session.to_dict()

    async def _reset(self) -> None:
        """Reinicia el estado liberando recursos. Solo para pruebas."""
        await self.shutdown()


# Instancia global consumida por los routers
camera_session_manager = CameraSessionManager()
