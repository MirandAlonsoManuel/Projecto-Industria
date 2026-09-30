"""
Gestor centralizado de sesión de cámara.

Garantías:
  - Un único recurso de captura abierto (MAX_CONCURRENT_CAMERAS = 1).
  - Un único cliente WebSocket activo (MAX_CONCURRENT_CLIENTS = 1).
  - Estado, último frame, métricas y errores encapsulados y consultables.

Para escalar a múltiples cámaras/clientes en el futuro:
  1. Incrementar MAX_CONCURRENT_CAMERAS y MAX_CONCURRENT_CLIENTS en limits.py.
  2. Cambiar `_session: CameraSession | None` por `_sessions: dict[str, CameraSession]`.
  3. Actualizar acquire/release para indexar por camera_id.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

from app.core.limits import FPS_WINDOW_FRAMES, MAX_ERROR_HISTORY
from app.services.camera_service import CameraCapture, open_camera


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
        now = time.monotonic()
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
class CameraSession:
    camera_id: str
    capture: CameraCapture
    status: SessionStatus = SessionStatus.STREAMING
    active_client: Optional[str] = None
    last_frame: Optional[np.ndarray] = None
    last_frame_ts: float = 0.0
    metrics: SessionMetrics = field(default_factory=SessionMetrics)
    errors: deque = field(
        default_factory=lambda: deque(maxlen=MAX_ERROR_HISTORY),
        repr=False,
    )

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
            "errors": [
                {"timestamp": e.timestamp, "message": e.message}
                for e in self.errors
            ],
        }


# ── Excepciones ───────────────────────────────────────────────────────────────

class SessionBusyError(RuntimeError):
    """La sesión ya tiene un cliente activo."""


class SessionCameraError(RuntimeError):
    """No se pudo abrir la fuente de cámara solicitada."""


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

    async def acquire(self, camera_id: str, client_id: str) -> CameraSession:
        """
        Reserva la sesión para el cliente dado.

        Raises:
            SessionBusyError: ya hay un cliente activo.
            SessionCameraError: la fuente de cámara no pudo abrirse.
        """
        async with self._lock:
            if self._session is not None and self._session.active_client is not None:
                raise SessionBusyError(
                    f"Sesión ocupada por el cliente '{self._session.active_client}'. "
                    "Solo se permite un cliente activo a la vez."
                )

            loop = asyncio.get_running_loop()
            capture = await loop.run_in_executor(None, open_camera, camera_id)
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
            return self._session

    async def release(self, client_id: str) -> None:
        """Libera la sesión y el recurso de captura si el cliente es el titular."""
        async with self._lock:
            if self._session is None:
                return
            if self._session.active_client != client_id:
                return
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._session.capture.release)
            self._session = None

    def get_status(self) -> dict:
        """Estado serializable de la sesión actual."""
        if self._session is None:
            return {"status": SessionStatus.IDLE.value, "active_client": None}
        return self._session.to_dict()

    async def _reset(self) -> None:
        """Reinicia el estado liberando recursos. Solo para pruebas."""
        async with self._lock:
            if self._session is not None:
                self._session.capture.release()
            self._session = None


# Instancia global consumida por los routers
camera_session_manager = CameraSessionManager()
