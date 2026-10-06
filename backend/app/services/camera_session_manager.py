"""
Gestor centralizado de sesión de cámara.

Acceso exclusivo (M03):
  - Un único recurso de captura abierto y un único cliente activo.
  - Un segundo cliente recibe SessionBusyError sin tocar la sesión activa.
  - El escaneo de cámaras nunca abre la fuente que está en uso.

Captura desacoplada (desacople captura–WebSocket):
  - Cada sesión tiene una tarea de captura (`_capture_loop`) que lee la cámara
    a TARGET_FPS y publica el frame completo en un FrameSlot. No conoce al
    cliente ni al WebSocket.
  - La cámara nunca se cierra con una lectura en curso: si read_frame() sigue
    bloqueado al liberar, el cierre del driver se difiere hasta que termine.

Ciclo de vida de la sesión (M07):

    idle ──start()──────────────▶ running ──connect_client()──▶ streaming
      ▲                              │  ▲                            │
      │                              │  └──── disconnect_client() ───┘
      └──────────── stop() ──────────┘        (sesión iniciada por operador)

  - Un cliente que se conecta con la sesión en `idle` la inicia por sí mismo
    (started_by = "client"). Al irse ese cliente, la cámara se cierra sola.
  - Una sesión iniciada con start() (started_by = "operator") sigue abierta y
    capturando en `running` cuando el cliente se va, lista para el siguiente.
  - Cada cliente consume su propio FrameSlot. Cuando un operador detiene la
    sesión, expulsa al cliente o el servicio se apaga, ese slot se cierra con
    el código de la causa (SESSION_STOPPED, CLIENT_DISCONNECTED o
    SERVICE_SHUTDOWN), y así el WebSocket sabe qué explicarle al cliente.
  - Mientras la cámara se cierra, el estado es `stopping`.
  - Cualquier operación fuera de orden lanza un SessionError con código estable.
  - shutdown() es idempotente: libera lo que haya y deja de aceptar sesiones.

Detección de cámara estancada (M10):

  - La sesión registra su última actividad: la apertura de la cámara o el
    último frame válido. Un frame vacío o un error del driver al leer ya no
    terminan la captura; cuentan como frames perdidos.
  - Un vigilante por sesión (`_watchdog_loop`) revisa cada WATCHDOG_INTERVAL_S
    cuánto tiempo lleva la cámara sin frames válidos. Pasado
    FRAME_STALE_TIMEOUT_S, la cámara está estancada, por uno de dos motivos:
    `no_frames` (responde, pero sin imagen) o `read_timeout` (la lectura quedó
    congelada en el driver).
  - La recuperación ocurre dentro de `_lock`: detiene la captura, cierra la
    cámara y solo entonces abre otra, con reintentos y esperas crecientes. El
    cliente conserva su conexión y su slot; solo nota una pausa.
  - Se respeta la regla del desacople: si la lectura sigue congelada, la cámara
    no se cierra a la fuerza. La recuperación se declara fallida, el cierre del
    driver se difiere y no se abre una segunda captura.
  - Si la recuperación falla, o la cámara vuelve a estancarse sin entregar un
    solo frame tras RECOVERY_MAX_ATTEMPTS recuperaciones seguidas, la sesión
    se cierra y el cliente recibe CAMERA_STALLED.

Métricas operativas (M12):

  - get_metrics() reúne en una sola consulta el estado de la cámara, el único
    cliente (0 o 1), los frames capturados, perdidos, enviados y saltados, las
    recuperaciones y el último error, para la sesión actual y acumulados desde
    que arrancó el servicio.
  - Ninguna salida expone credenciales: la cámara se abre con la fuente real,
    pero estado, métricas, eventos, errores y logs usan la versión enmascarada
    (ver app/services/redaction.py).

Concurrencia: toda transición ocurre dentro de `_lock`. Cada operación se
ejecuta en una tarea propia del gestor (`_run_detached`): si quien la pidió se
cancela, la operación termina igual. Esto es necesario porque anyio, que usan
Starlette y FastAPI, repite la cancelación en cada `await` del código cancelado.

Compatibilidad: get_status() conserva el contrato de M01 (en `idle` responde
exactamente {"status": "idle", "active_client": None}); el estado completo del
ciclo de vida se consulta con get_lifecycle_status().

Límite conocido: el candado vive en memoria del proceso. El servicio debe
ejecutarse con un solo worker de uvicorn para que la exclusión sea real.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

import numpy as np

from app.core.limits import (
    FPS_WINDOW_FRAMES,
    FRAME_STALE_TIMEOUT_S,
    LIFECYCLE_EVENT_HISTORY,
    MAX_ERROR_HISTORY,
    RECOVERY_BACKOFF_S,
    RECOVERY_MAX_ATTEMPTS,
    TARGET_FPS,
    WATCHDOG_INTERVAL_S,
)
from app.services.camera_service import CameraCapture, open_camera
from app.services.frame_slot import FramePacket, FrameSlot, FrameSlotClosed
from app.services.redaction import redact_source, redact_text

logger = logging.getLogger(__name__)

NO_FRAMES_CODE = "CAMERA_NO_FRAMES"
READ_ERROR_CODE = "CAMERA_READ_ERROR"
STALLED_CODE = "CAMERA_STALLED"
_NO_FRAMES_MESSAGE = "La cámara dejó de enviar frames."

# Descripción para el cliente cuando su sesión termina por una acción externa
CLIENT_END_DESCRIPTIONS: dict[str, str] = {
    "SESSION_STOPPED": "La sesión de cámara fue detenida.",
    "CLIENT_DISCONNECTED": "Un operador cerró esta conexión.",
    "SERVICE_SHUTDOWN": "El servicio se está apagando.",
    STALLED_CODE: "La cámara dejó de producir frames y no se pudo recuperar.",
}


# ── Estado ────────────────────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    STREAMING = "streaming"
    RECOVERING = "recovering"
    ERROR = "error"


class StartedBy(str, Enum):
    CLIENT = "client"
    OPERATOR = "operator"


class LifecycleEvent(str, Enum):
    STARTED = "started"
    CLIENT_CONNECTED = "client_connected"
    CLIENT_DISCONNECTED = "client_disconnected"
    STOPPED = "stopped"
    SHUTDOWN = "shutdown"
    STALLED = "stalled"
    RECOVERED = "recovered"
    RECOVERY_FAILED = "recovery_failed"


class StallReason(str, Enum):
    NO_FRAMES = "no_frames"          # la cámara responde, pero solo con frames vacíos
    READ_TIMEOUT = "read_timeout"    # la lectura quedó congelada en el driver


# ── Estructuras de datos ──────────────────────────────────────────────────────

@dataclass
class ErrorRecord:
    timestamp: float
    message: str


@dataclass
class LifecycleRecord:
    seq: int
    event: LifecycleEvent
    timestamp: float
    camera_id: Optional[str] = None
    client_id: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "event": self.event.value,
            "timestamp": self.timestamp,
            "camera_id": self.camera_id,
            "client_id": self.client_id,
            "reason": self.reason,
        }


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
class RecoveryInfo:
    """Resumen de las recuperaciones de la sesión."""

    total: int = 0
    failed: int = 0
    # Recuperaciones seguidas sin que llegue un solo frame válido
    consecutive: int = 0
    last_reason: Optional[str] = None
    last_started_ts: Optional[float] = None
    last_attempts: int = 0
    last_result: Optional[str] = None   # "recovered" o "failed"

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "failed": self.failed,
            "consecutive": self.consecutive,
            "last_reason": self.last_reason,
            "last_started_ts": self.last_started_ts,
            "last_attempts": self.last_attempts,
            "last_result": self.last_result,
        }


@dataclass
class CameraSession:
    camera_id: str
    capture: CameraCapture
    status: SessionStatus = SessionStatus.STREAMING
    active_client: Optional[str] = None
    started_by: StartedBy = StartedBy.CLIENT
    last_frame: Optional[np.ndarray] = None
    last_frame_ts: float = 0.0
    metrics: SessionMetrics = field(default_factory=SessionMetrics)
    delivery: DeliveryMetrics = field(default_factory=DeliveryMetrics)
    errors: deque = field(
        default_factory=lambda: deque(maxlen=MAX_ERROR_HISTORY),
        repr=False,
    )
    # Slot del cliente actual; la captura publica siempre en el vigente
    frames: FrameSlot = field(default_factory=FrameSlot, repr=False)
    capture_task: Optional[asyncio.Task] = field(default=None, repr=False)
    # Lectura de cámara en curso (o la última): mientras no termine, no se cierra.
    pending_read: Optional[asyncio.Future] = field(default=None, repr=False)
    closed: bool = False
    # Vigilancia de actividad (M10)
    watchdog_task: Optional[asyncio.Task] = field(default=None, repr=False)
    last_activity: float = field(default_factory=time.monotonic, repr=False)
    last_activity_ts: float = field(default_factory=time.time)
    reading_since: Optional[float] = field(default=None, repr=False)
    recovering: bool = False
    recovery: RecoveryInfo = field(default_factory=RecoveryInfo)
    # Métricas (M12)
    errors_total: int = 0
    connected_since: Optional[float] = None

    @property
    def public_id(self) -> Optional[str]:
        """Identificador de la cámara sin credenciales, para cualquier salida."""
        return redact_source(self.camera_id)

    @property
    def capture_alive(self) -> bool:
        """La tarea de captura sigue corriendo (no terminó por falta de frames o error)."""
        return self.capture_task is not None and not self.capture_task.done()

    def update_frame(self, frame: Optional[np.ndarray]) -> None:
        """Actualiza el último frame y avanza las métricas."""
        if frame is None:
            self.metrics.tick_drop()
            return
        self.last_frame = frame
        self.last_frame_ts = time.time()
        self.metrics.tick_frame()
        self.mark_activity()
        self.recovery.consecutive = 0

    def mark_activity(self) -> None:
        self.last_activity = time.monotonic()
        self.last_activity_ts = time.time()

    @property
    def seconds_without_frames(self) -> float:
        return time.monotonic() - self.last_activity

    def record_error(self, message: str) -> None:
        """Registra un error y transiciona el estado a ERROR."""
        self.note_error(message)
        self.status = SessionStatus.ERROR

    def note_error(self, message: str) -> None:
        """Registra un error sin cambiar el estado (por ejemplo, una lectura fallida)."""
        self.errors.append(
            ErrorRecord(timestamp=time.time(), message=redact_text(message, self.camera_id))
        )
        self.errors_total += 1

    def to_dict(self) -> dict:
        return {
            "camera_id": self.public_id,
            "status": self.status.value,
            "active_client": self.active_client,
            "started_by": self.started_by.value,
            "last_frame_ts": self.last_frame_ts or None,
            "last_activity_ts": self.last_activity_ts,
            "seconds_without_frames": round(self.seconds_without_frames, 2),
            "recovery": self.recovery.to_dict(),
            "metrics": self.metrics.to_dict(),
            "delivery": self.delivery.to_dict(),
            "errors": [
                {"timestamp": e.timestamp, "message": redact_text(e.message, self.camera_id)}
                for e in self.errors
            ],
        }


@dataclass
class ServiceCounters:
    """Acumulados de las sesiones ya cerradas, desde que arrancó el servicio."""

    started_at: float = field(default_factory=time.time)
    started_mono: float = field(default_factory=time.monotonic)
    sessions_started: int = 0
    client_connections: int = 0
    client_rejections: int = 0
    frames_captured: int = 0
    frames_dropped: int = 0
    frames_sent: int = 0
    frames_skipped: int = 0
    recoveries: int = 0
    recoveries_failed: int = 0
    errors_total: int = 0
    last_error: Optional[ErrorRecord] = None

    def absorb(self, session: "CameraSession") -> None:
        """Suma los contadores de una sesión que terminó."""
        self.frames_captured += session.metrics.frames_total
        self.frames_dropped += session.metrics.frames_dropped
        self.frames_sent += session.delivery.frames_sent
        self.frames_skipped += session.delivery.frames_skipped
        self.recoveries += session.recovery.total - session.recovery.failed
        self.recoveries_failed += session.recovery.failed
        self.errors_total += session.errors_total
        if session.errors:
            self.last_error = session.errors[-1]


# ── Excepciones ───────────────────────────────────────────────────────────────

class SessionError(RuntimeError):
    """Base de los errores controlados del ciclo de vida."""

    code = "SESSION_ERROR"
    http_status = 409


class SessionBusyError(SessionError):
    """La sesión ya tiene un cliente activo."""

    code = "CAMERA_BUSY"


class SessionCameraError(SessionError):
    """No se pudo abrir la fuente de cámara solicitada."""

    code = "CAMERA_UNAVAILABLE"
    http_status = 503


class SessionAlreadyActiveError(SessionError):
    """Se pidió iniciar una sesión que ya está iniciada."""

    code = "SESSION_ALREADY_ACTIVE"


class SessionNotActiveError(SessionError):
    """Se pidió detener una sesión que no existe."""

    code = "SESSION_NOT_ACTIVE"


class NoClientConnectedError(SessionError):
    """Se pidió desconectar a un cliente, pero no hay ninguno."""

    code = "NO_CLIENT_CONNECTED"


class CameraMismatchError(SessionError):
    """El cliente pidió una cámara distinta a la de la sesión activa."""

    code = "CAMERA_MISMATCH"


class ServiceShuttingDownError(SessionError):
    """El servicio está apagándose y no acepta sesiones nuevas."""

    code = "SERVICE_SHUTTING_DOWN"
    http_status = 503


class ClientSessionEndedError(SessionError):
    """La sesión del cliente terminó por una acción externa.

    El código indica la causa para que el WebSocket se la explique al cliente:
    SESSION_STOPPED, CLIENT_DISCONNECTED o SERVICE_SHUTDOWN.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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


class _Request:
    """Marca si quien pidió una operación ya no espera su resultado."""

    __slots__ = ("abandoned",)

    def __init__(self) -> None:
        self.abandoned = False


# ── Captura ───────────────────────────────────────────────────────────────────

async def _capture_loop(session: CameraSession) -> None:
    """
    Ciclo de adquisición: lee la cámara a su ritmo y publica en el slot vigente.

    No conoce al cliente ni al WebSocket. Solo termina cuando la tarea se
    cancela al liberar la sesión o al recuperarla. Un frame vacío o un error
    del driver cuentan como frames perdidos: decidir si la cámara está
    estancada le corresponde al vigilante, no a una lectura aislada (M10).
    """
    loop = asyncio.get_running_loop()
    interval = 1.0 / TARGET_FPS
    while True:
        t0 = time.monotonic()

        read = loop.run_in_executor(None, session.capture.read_frame)
        session.pending_read = read
        session.reading_since = t0
        try:
            frame = await asyncio.shield(read)
        except asyncio.CancelledError:
            # La lectura sigue en su hilo: se le da un margen para terminar.
            # Si sigue bloqueada, el cierre de la cámara queda diferido
            # (ver _close_capture); aquí nunca se libera a mitad de un read.
            await asyncio.wait([read], timeout=FRAME_STALE_TIMEOUT_S)
            raise
        except Exception as exc:
            logger.warning(
                "Error del driver al leer la cámara '%s': %s",
                session.public_id,
                redact_text(str(exc), session.camera_id),
            )
            session.note_error(f"Error al leer frame: {exc}")
            frame = None
        finally:
            session.reading_since = None

        session.update_frame(frame)
        if frame is not None:
            session.frames.publish(frame, session.last_frame_ts)

        sleep_for = interval - (time.monotonic() - t0)
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)


async def _cancel_and_wait(task: Optional[asyncio.Task]) -> None:
    if task is not None and not task.done() and task is not asyncio.current_task():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _stop_capture(session: CameraSession, close_slot: bool = True) -> None:
    """Cancela la tarea de captura y espera a que termine. No propaga errores.

    Durante una recuperación el slot no se cierra: el cliente sigue esperando
    frames en él mientras la cámara se reabre.
    """
    task = session.capture_task
    session.capture_task = None
    await _cancel_and_wait(task)
    if close_slot:
        session.frames.close("Sesión de cámara liberada.")


def _release_when_read_ends(read: asyncio.Future, capture: CameraCapture) -> None:
    """Cierra la cámara en cuanto termine la lectura que seguía bloqueada."""
    loop = read.get_loop()

    def _release(_: asyncio.Future) -> None:
        loop.run_in_executor(None, _release_quietly, capture)

    read.add_done_callback(_release)


# ── Gestor ────────────────────────────────────────────────────────────────────

class CameraSessionManager:
    """
    Singleton que gestiona la única sesión de cámara y su ciclo de vida.

    Operaciones públicas:
      start / stop                       — administración explícita de la sesión
      connect_client / disconnect_client — entrada y salida del único cliente
      force_disconnect                   — expulsión del cliente por un operador
      next_frame                         — siguiente frame del slot de un cliente
      shutdown                           — apagado global idempotente
      get_status / get_lifecycle_status  — estado (contrato M01) y ciclo de vida

    acquire / release se conservan como alias de connect_client /
    disconnect_client por compatibilidad con M01, M02, M03 y el stream_runner.
    """

    def __init__(
        self,
        *,
        stale_timeout_s: Optional[float] = None,
        watchdog_interval_s: Optional[float] = None,
        recovery_attempts: Optional[int] = None,
        recovery_backoff_s: Optional[float] = None,
    ) -> None:
        # Los valores por defecto se leen de limits.py al crear el gestor
        self.stale_timeout_s = (
            FRAME_STALE_TIMEOUT_S if stale_timeout_s is None else stale_timeout_s
        )
        self.watchdog_interval_s = (
            WATCHDOG_INTERVAL_S if watchdog_interval_s is None else watchdog_interval_s
        )
        self.recovery_attempts = (
            RECOVERY_MAX_ATTEMPTS if recovery_attempts is None else recovery_attempts
        )
        self.recovery_backoff_s = (
            RECOVERY_BACKOFF_S if recovery_backoff_s is None else recovery_backoff_s
        )
        self._session: Optional[CameraSession] = None
        # Sesión que se está cerrando: sus métricas siguen contando hasta absorberse
        self._closing: Optional[CameraSession] = None
        self._service = ServiceCounters()
        self._lock = asyncio.Lock()
        self._events: deque[LifecycleRecord] = deque(maxlen=LIFECYCLE_EVENT_HISTORY)
        self._seq = 0
        # Slot entregado a cada cliente; se retira cuando el cliente se desconecta
        self._client_slots: dict[str, FrameSlot] = {}
        self._accepting = True
        # Cámara que se está cerrando en este momento (estado transitorio `stopping`)
        self._stopping_camera: Optional[str] = None

    # ── Consultas ────────────────────────────────────────────────────────────

    @property
    def session(self) -> Optional[CameraSession]:
        return self._session

    @property
    def is_busy(self) -> bool:
        return self._session is not None

    @property
    def is_accepting(self) -> bool:
        return self._accepting

    @property
    def state(self) -> SessionStatus:
        """Estado del ciclo de vida, independiente de la salud de la sesión."""
        if self._session is None:
            if self._stopping_camera is not None:
                return SessionStatus.STOPPING
            return SessionStatus.IDLE
        if self._session.recovering:
            return SessionStatus.RECOVERING
        if self._session.active_client is not None:
            return SessionStatus.STREAMING
        return SessionStatus.RUNNING

    def get_status(self) -> dict:
        """Estado serializable de la sesión actual (contrato M01)."""
        if self._session is None:
            return {"status": SessionStatus.IDLE.value, "active_client": None}
        return self._session.to_dict()

    def get_lifecycle_status(self) -> dict:
        """Estado de la sesión más el ciclo de vida y su historial de eventos."""
        status = self.get_status()
        if self._session is None and self._stopping_camera is not None:
            status["camera_id"] = self._stopping_camera
        status["state"] = self.state.value
        status["stale_timeout_s"] = self.stale_timeout_s
        status["accepting_clients"] = self._accepting
        status["events"] = [record.to_dict() for record in self._events]
        return status

    def get_metrics(self) -> dict:
        """
        Métricas operativas de la única cámara (M12).

        `session` describe la sesión actual (en cero si no hay); `since_start`
        suma las sesiones cerradas más la actual, desde que arrancó el servicio.
        Ningún campo contiene credenciales.
        """
        session = self._session or self._closing
        svc = self._service
        now = time.time()

        if session is not None:
            frames_session = {
                "captured": session.metrics.frames_total,
                "dropped": session.metrics.frames_dropped,
                "sent": session.delivery.frames_sent,
                "skipped": session.delivery.frames_skipped,
            }
            recoveries_session = {
                "recovered": session.recovery.total - session.recovery.failed,
                "failed": session.recovery.failed,
            }
            errors_session = session.errors_total
        else:
            frames_session = {"captured": 0, "dropped": 0, "sent": 0, "skipped": 0}
            recoveries_session = {"recovered": 0, "failed": 0}
            errors_session = 0

        frames_total = {
            "captured": svc.frames_captured + frames_session["captured"],
            "dropped": svc.frames_dropped + frames_session["dropped"],
            "sent": svc.frames_sent + frames_session["sent"],
            "skipped": svc.frames_skipped + frames_session["skipped"],
        }

        last_error_record = (
            session.errors[-1] if session is not None and session.errors else svc.last_error
        )
        last_error = None
        if last_error_record is not None:
            last_error = {
                "timestamp": last_error_record.timestamp,
                "message": redact_text(
                    last_error_record.message, session.camera_id if session else None
                ),
            }

        active = self._session
        client_connected = 1 if active is not None and active.active_client is not None else 0

        return {
            "timestamp": now,
            "camera": {
                "camera_id": session.public_id if session is not None else None,
                "state": self.state.value,
                "health": (
                    None if session is None
                    else "error" if session.status == SessionStatus.ERROR
                    else "ok"
                ),
                "started_by": session.started_by.value if session is not None else None,
                "fps_current": round(session.metrics.fps_current, 2) if session else 0.0,
                "uptime_seconds": round(session.metrics.uptime_seconds, 1) if session else 0.0,
                "last_activity_ts": session.last_activity_ts if session else None,
                "seconds_without_frames": (
                    round(session.seconds_without_frames, 2) if session else None
                ),
                "stale_timeout_s": self.stale_timeout_s,
            },
            "client": {
                "connected": client_connected,
                "client_id": active.active_client if client_connected else None,
                "connected_since": active.connected_since if client_connected else None,
                "connections_total": svc.client_connections,
                "rejections_total": svc.client_rejections,
            },
            "frames": {"session": frames_session, "since_start": frames_total},
            "recoveries": {
                "session": recoveries_session,
                "since_start": {
                    "recovered": svc.recoveries + recoveries_session["recovered"],
                    "failed": svc.recoveries_failed + recoveries_session["failed"],
                },
            },
            "errors": {
                "session": errors_session,
                "since_start": svc.errors_total + errors_session,
            },
            "last_error": last_error,
            "service": {
                "started_at": svc.started_at,
                "uptime_seconds": round(time.monotonic() - svc.started_mono, 1),
                "sessions_started": svc.sessions_started,
                "accepting_clients": self._accepting,
            },
        }

    # ── Ejecución ────────────────────────────────────────────────────────────

    async def _run_blocking(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_orphan: Optional[Callable[[Any], None]] = None,
    ) -> Any:
        """Ejecuta una operación bloqueante de hardware en un hilo.

        Si la espera se cancela, `on_orphan` cierra el recurso que el hilo
        llegue a producir y que ya nadie va a usar.
        """
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

    async def _run_detached(
        self, coro: Awaitable[Any], request: Optional[_Request] = None
    ) -> Any:
        """
        Ejecuta la operación en una tarea propia y espera su resultado.

        Si quien espera se cancela, la tarea sigue hasta terminar (y conserva
        el candado mientras tanto). `request.abandoned` le avisa que nadie
        recibirá el resultado, para que deshaga lo que ya no tiene dueño.
        """
        task = asyncio.ensure_future(coro)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if request is not None:
                request.abandoned = True
            raise

    # ── Transiciones internas (requieren `_lock` tomado) ─────────────────────

    def _record(
        self,
        event: LifecycleEvent,
        *,
        camera_id: Optional[str] = None,
        client_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        camera_id = redact_source(camera_id)
        self._seq += 1
        self._events.append(
            LifecycleRecord(
                seq=self._seq,
                event=event,
                timestamp=time.time(),
                camera_id=camera_id,
                client_id=client_id,
                reason=reason,
            )
        )
        logger.info(
            "Ciclo de vida: %s (cámara=%s, cliente=%s, motivo=%s)",
            event.value, camera_id, client_id, reason,
        )

    def _ensure_accepting(self) -> None:
        if not self._accepting:
            raise ServiceShuttingDownError(
                "El servicio se está apagando y no acepta sesiones nuevas."
            )

    async def _open_session(self, camera_id: str, started_by: StartedBy) -> CameraSession:
        try:
            capture = await self._run_blocking(
                open_camera, camera_id, on_orphan=_release_quietly
            )
        except Exception as exc:
            raise SessionCameraError(
                f"Error del driver al abrir la cámara '{redact_source(camera_id)}': "
                f"{redact_text(str(exc), camera_id)}"
            ) from exc

        if capture is None:
            raise SessionCameraError(
                f"No se pudo abrir la cámara '{redact_source(camera_id)}'. "
                "Verifique que esté conectada y no esté en uso."
            )

        session = CameraSession(
            camera_id=camera_id,
            capture=capture,
            status=SessionStatus.RUNNING,
            started_by=started_by,
            metrics=SessionMetrics(started_at=time.monotonic()),
        )
        session.capture_task = asyncio.create_task(_capture_loop(session))
        session.watchdog_task = asyncio.create_task(self._watchdog_loop(session))
        self._session = session
        self._service.sessions_started += 1
        self._record(LifecycleEvent.STARTED, camera_id=camera_id, reason=started_by.value)
        return session

    def _detach_client(
        self, session: CameraSession, reason: str, client_code: Optional[str]
    ) -> None:
        """Retira al cliente activo y cierra su slot con la causa, si la hay."""
        client_id = session.active_client
        session.active_client = None
        session.connected_since = None
        if session.status == SessionStatus.STREAMING:
            session.status = SessionStatus.RUNNING
        if client_code is not None:
            session.frames.close(CLIENT_END_DESCRIPTIONS[client_code], code=client_code)
        else:
            session.frames.close("El cliente se desconectó.")
        self._record(
            LifecycleEvent.CLIENT_DISCONNECTED,
            camera_id=session.camera_id,
            client_id=client_id,
            reason=reason,
        )

    def _keep_or_close_after_client(self, session: CameraSession) -> bool:
        """
        Decide si la sesión sigue abierta tras irse su cliente.

        Sigue abierta solo si la inició un operador y la captura sigue viva; en
        ese caso el siguiente cliente recibe un slot nuevo.
        """
        if session.started_by == StartedBy.OPERATOR and session.capture_alive:
            session.frames = FrameSlot()
            return True
        return False

    async def _close_session(self, reason: str, client_code: str) -> None:
        session = self._session
        if session.active_client is not None:
            self._detach_client(session, reason, client_code)
        # La sesión se retira antes de cerrar: aunque el driver falle, el recurso
        # no queda secuestrado. `_lock` sigue tomado, así nadie abre mientras tanto.
        session.closed = True
        self._session = None
        self._closing = session
        self._stopping_camera = session.public_id
        try:
            await self._close_capture(session)
        finally:
            self._stopping_camera = None
            self._closing = None
            self._service.absorb(session)
        self._record(LifecycleEvent.STOPPED, camera_id=session.camera_id, reason=reason)

    async def _close_capture(self, session: CameraSession) -> None:
        """
        Detiene la captura y cierra la cámara, nunca a mitad de una lectura.

        Si read_frame() sigue bloqueado tras detener la captura, release() del
        driver no se ejecuta ahora: queda programado para cuando esa lectura
        termine. La sesión se da por libre de inmediato para no retener al
        siguiente cliente.
        """
        watchdog = session.watchdog_task
        session.watchdog_task = None
        try:
            await _cancel_and_wait(watchdog)
            await _stop_capture(session)
        finally:
            read = session.pending_read
            if read is not None and not read.done():
                logger.warning(
                    "Lectura de la cámara '%s' aún bloqueada; el cierre se "
                    "difiere hasta que termine",
                    session.public_id,
                )
                _release_when_read_ends(read, session.capture)
            else:
                await self._run_blocking(_release_quietly, session.capture)

    # ── Operaciones públicas ─────────────────────────────────────────────────

    async def start(
        self, camera_id: str, started_by: StartedBy = StartedBy.OPERATOR
    ) -> CameraSession:
        """
        Abre la cámara y deja la sesión en `running`, capturando y sin cliente.

        Raises:
            SessionAlreadyActiveError: ya hay una sesión iniciada.
            SessionCameraError: la fuente no pudo abrirse.
            ServiceShuttingDownError: el servicio se está apagando.
        """
        return await self._run_detached(self._start(camera_id, started_by))

    async def _start(self, camera_id: str, started_by: StartedBy) -> CameraSession:
        async with self._lock:
            self._ensure_accepting()
            if self._session is not None:
                raise SessionAlreadyActiveError(
                    f"Ya hay una sesión activa con la cámara '{self._session.public_id}'."
                )
            return await self._open_session(camera_id, started_by)

    async def stop(self, reason: str = "operator") -> None:
        """
        Cierra la sesión. Si hay un cliente conectado, su slot se cierra con
        SESSION_STOPPED.

        Raises:
            SessionNotActiveError: no hay sesión que detener.
        """
        await self._run_detached(self._stop(reason))

    async def _stop(self, reason: str) -> None:
        async with self._lock:
            if self._session is None:
                raise SessionNotActiveError("No hay una sesión activa que detener.")
            await self._close_session(reason, client_code="SESSION_STOPPED")

    async def connect_client(self, camera_id: str, client_id: str) -> CameraSession:
        """
        Asigna la sesión al cliente. Si la sesión está en `idle`, la inicia.

        El cliente consume `session.frames` tal como está al conectarse; ese
        slot es suyo durante toda la conexión.

        Raises:
            SessionBusyError: ya hay un cliente activo.
            CameraMismatchError: la sesión activa usa otra cámara.
            SessionCameraError: la fuente no pudo abrirse.
            ServiceShuttingDownError: el servicio se está apagando.
        """
        request = _Request()
        try:
            return await self._run_detached(
                self._connect_client(camera_id, client_id, request), request
            )
        except (SessionBusyError, CameraMismatchError, ServiceShuttingDownError):
            self._service.client_rejections += 1
            raise

    async def _connect_client(
        self, camera_id: str, client_id: str, request: _Request
    ) -> Optional[CameraSession]:
        async with self._lock:
            if request.abandoned:
                return None
            self._ensure_accepting()
            session = self._session
            if session is not None and session.active_client is not None:
                raise SessionBusyError(
                    "La cámara ya está en uso por otro cliente. "
                    "Solo se permite un cliente activo a la vez."
                )
            if session is not None and session.camera_id != camera_id:
                raise CameraMismatchError(
                    f"La sesión activa usa la cámara '{session.public_id}', "
                    f"no '{redact_source(camera_id)}'."
                )
            if session is not None and not session.capture_alive:
                # La captura de una sesión de operador terminó sola: se reabre
                await self._close_session("capture_ended", client_code="SESSION_STOPPED")
                session = None

            opened_here = session is None
            if opened_here:
                session = await self._open_session(camera_id, StartedBy.CLIENT)

            if request.abandoned:
                # El cliente se fue mientras se abría la cámara
                if opened_here:
                    await self._close_session("abandoned", client_code="SESSION_STOPPED")
                return None

            session.active_client = client_id
            session.connected_since = time.time()
            if session.status != SessionStatus.ERROR:
                session.status = SessionStatus.STREAMING
            self._client_slots[client_id] = session.frames
            self._service.client_connections += 1
            self._record(
                LifecycleEvent.CLIENT_CONNECTED, camera_id=camera_id, client_id=client_id
            )
            return session

    async def disconnect_client(self, client_id: str, reason: str = "client_left") -> bool:
        """
        Retira al cliente que se va. Es idempotente y seguro para un `finally`.

        Si la sesión la inició el propio cliente, la cámara también se cierra.

        Returns:
            True si el cliente era el titular y se retiró; False en otro caso.
        """
        return await self._run_detached(self._disconnect_client(client_id, reason))

    async def _disconnect_client(self, client_id: str, reason: str) -> bool:
        async with self._lock:
            self._client_slots.pop(client_id, None)
            session = self._session
            if session is None or session.active_client != client_id:
                return False
            self._detach_client(session, reason, client_code=None)
            if not self._keep_or_close_after_client(session):
                await self._close_session("auto_stop", client_code="SESSION_STOPPED")
            return True

    async def force_disconnect(self) -> str:
        """
        Expulsa al cliente activo por decisión de un operador.

        Su slot se cierra con CLIENT_DISCONNECTED. Si la sesión la había
        iniciado el cliente, la cámara también se cierra.

        Returns:
            El identificador del cliente desconectado.

        Raises:
            NoClientConnectedError: no hay cliente que desconectar.
        """
        return await self._run_detached(self._force_disconnect())

    async def _force_disconnect(self) -> str:
        async with self._lock:
            session = self._session
            if session is None or session.active_client is None:
                raise NoClientConnectedError("No hay un cliente conectado.")
            client_id = session.active_client
            self._detach_client(session, "operator", client_code="CLIENT_DISCONNECTED")
            if not self._keep_or_close_after_client(session):
                await self._close_session("auto_stop", client_code="SESSION_STOPPED")
            return client_id

    async def next_frame(self, client_id: str, after_seq: int = 0) -> FramePacket:
        """
        Siguiente frame del slot del cliente, posterior a `after_seq`.

        Raises:
            ClientSessionEndedError: la sesión del cliente terminó; `code`
                indica la causa (SESSION_STOPPED, CLIENT_DISCONNECTED,
                SERVICE_SHUTDOWN, CAMERA_NO_FRAMES, ...).
        """
        slot = self._client_slots.get(client_id)
        if slot is None:
            raise ClientSessionEndedError("SESSION_STOPPED")
        try:
            return await slot.next(after_seq)
        except FrameSlotClosed as exc:
            raise ClientSessionEndedError(exc.code) from exc

    async def shutdown(self) -> bool:
        """
        Apagado global: libera la sesión, deja de aceptar sesiones nuevas y
        registra el evento. Es idempotente.

        Returns:
            True si había una sesión que liberar; False si ya estaba en `idle`.
        """
        return await self._run_detached(self._shutdown())

    async def _shutdown(self) -> bool:
        async with self._lock:
            self._accepting = False
            released = self._session is not None
            if released:
                await self._close_session("shutdown", client_code="SERVICE_SHUTDOWN")
            self._record(
                LifecycleEvent.SHUTDOWN,
                reason="released" if released else "already_idle",
            )
            return released

    # ── Detección y recuperación de cámara estancada (M10) ──────────────────

    def _stall_reason(self, session: CameraSession) -> Optional[StallReason]:
        """
        Motivo del estancamiento, o None si la cámara está activa.

        Que haya una lectura en curso no basta para decir que está congelada:
        la captura lee continuamente, así que casi siempre hay una. Una lectura
        se considera congelada cuando lleva más de la mitad del umbral; una
        lectura normal dura un intervalo de captura (unos 33 ms a 30 FPS).
        """
        if session.closed or session.recovering:
            return None
        if session.seconds_without_frames <= self.stale_timeout_s:
            return None
        reading_since = session.reading_since
        if (
            reading_since is not None
            and time.monotonic() - reading_since > self.stale_timeout_s / 2
        ):
            return StallReason.READ_TIMEOUT
        return StallReason.NO_FRAMES

    def check_stall(self) -> Optional[StallReason]:
        """Indica si la cámara de la sesión actual está estancada y por qué."""
        session = self._session
        return None if session is None else self._stall_reason(session)

    async def _watchdog_loop(self, session: CameraSession) -> None:
        """Vigila la actividad de la sesión y dispara la recuperación."""
        while not session.closed:
            await asyncio.sleep(self.watchdog_interval_s)
            reason = self._stall_reason(session)
            if reason is not None:
                await self.recover(reason)

    async def recover(self, reason: StallReason) -> bool:
        """
        Recuperación controlada de una cámara estancada.

        Returns:
            True si la cámara se recuperó. False si no había nada que recuperar
            (la cámara volvió sola o la sesión terminó) o si la recuperación
            falló; en ese caso la sesión se cierra y el cliente recibe
            CAMERA_STALLED.
        """
        return await self._run_detached(self._recover(reason))

    async def _recover(self, reason: StallReason) -> bool:
        async with self._lock:
            session = self._session
            # Se confirma dentro del candado: el estado pudo cambiar mientras se esperaba
            if session is None or self._stall_reason(session) is None:
                return False

            session.recovering = True
            session.status = SessionStatus.RECOVERING
            info = session.recovery
            info.total += 1
            info.consecutive += 1
            info.last_reason = reason.value
            info.last_started_ts = time.time()
            info.last_attempts = 0
            info.last_result = None
            self._record(
                LifecycleEvent.STALLED,
                camera_id=session.camera_id,
                client_id=session.active_client,
                reason=reason.value,
            )

            # 1. Detener la captura sin cerrar el slot del cliente
            await _stop_capture(session, close_slot=False)

            # 2. Nunca cerrar a mitad de una lectura: si sigue congelada, no es
            #    seguro abrir otra captura del mismo dispositivo.
            read = session.pending_read
            if read is not None and not read.done():
                _release_when_read_ends(read, session.capture)
                await self._fail_recovery(session, reason, "lectura congelada; cierre diferido")
                return False

            await self._run_blocking(_release_quietly, session.capture)

            # 3. Si la cámara ya se recuperó varias veces sin entregar un solo
            #    frame, reabrirla otra vez no tiene sentido.
            if info.consecutive > self.recovery_attempts:
                await self._fail_recovery(
                    session, reason, f"sin frames tras {self.recovery_attempts} recuperaciones"
                )
                return False

            # 4. Reabrir con esperas crecientes
            for attempt in range(1, self.recovery_attempts + 1):
                await asyncio.sleep(self.recovery_backoff_s * 2 ** (attempt - 1))
                info.last_attempts = attempt
                capture = await self._try_open(session.camera_id)
                if capture is None:
                    continue
                session.capture = capture
                session.pending_read = None
                session.mark_activity()
                session.recovering = False
                session.status = (
                    SessionStatus.STREAMING
                    if session.active_client is not None
                    else SessionStatus.RUNNING
                )
                info.last_result = "recovered"
                session.capture_task = asyncio.create_task(_capture_loop(session))
                self._record(
                    LifecycleEvent.RECOVERED,
                    camera_id=session.camera_id,
                    client_id=session.active_client,
                    reason=f"{reason.value}; intento {attempt}",
                )
                return True

            await self._fail_recovery(
                session, reason, f"no se pudo reabrir en {self.recovery_attempts} intentos"
            )
            return False

    async def _try_open(self, camera_id: str) -> Optional[CameraCapture]:
        try:
            return await self._run_blocking(
                open_camera, camera_id, on_orphan=_release_quietly
            )
        except Exception as exc:
            logger.warning(
                "Error del driver al reabrir la cámara '%s': %s",
                redact_source(camera_id),
                redact_text(str(exc), camera_id),
            )
            return None

    async def _fail_recovery(
        self, session: CameraSession, reason: StallReason, detail: str
    ) -> None:
        """Cierra la sesión tras una recuperación fallida.

        La captura ya está liberada o con su cierre diferido: no se vuelve a tocar.
        """
        session.recovery.last_result = "failed"
        session.recovery.failed += 1
        session.recovering = False
        session.record_error(f"Recuperación fallida ({reason.value}): {detail}")
        self._record(
            LifecycleEvent.RECOVERY_FAILED,
            camera_id=session.camera_id,
            client_id=session.active_client,
            reason=f"{reason.value}; {detail}",
        )
        if session.active_client is not None:
            self._detach_client(session, "recovery_failed", client_code=STALLED_CODE)
        session.closed = True
        self._session = None
        self._service.absorb(session)
        session.frames.close("Sesión de cámara liberada.")
        self._record(LifecycleEvent.STOPPED, camera_id=session.camera_id, reason="recovery_failed")
        # El estado queda consistente antes de cualquier espera; luego se retira el vigilante
        watchdog = session.watchdog_task
        session.watchdog_task = None
        await _cancel_and_wait(watchdog)

    async def scan_cameras(
        self, detector: Callable[..., list[dict]]
    ) -> list[dict]:
        """
        Escanea cámaras sin abrir nunca la que está en uso.

        El sondeo ocurre dentro del candado, de modo que ninguna conexión puede
        adquirir la cámara entre la consulta del estado y la apertura de prueba.
        La cámara activa se reporta como `in_use` sin tocar el dispositivo.
        """
        return await self._run_detached(self._scan_cameras(detector))

    async def _scan_cameras(self, detector: Callable[..., list[dict]]) -> list[dict]:
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

    # ── Compatibilidad con M01, M02 y M03 ────────────────────────────────────

    async def acquire(self, camera_id: str, client_id: str) -> CameraSession:
        """Alias de connect_client."""
        return await self.connect_client(camera_id, client_id)

    async def release(self, client_id: str) -> bool:
        """Alias de disconnect_client."""
        return await self.disconnect_client(client_id)

    async def _reset(self) -> None:
        """Reinicia el gestor a su estado inicial. Solo para pruebas."""
        await self.shutdown()
        async with self._lock:
            self._accepting = True
            self._events.clear()
            self._client_slots.clear()
            self._seq = 0


# Instancia global consumida por los routers
camera_session_manager = CameraSessionManager()
