"""
Gestor centralizado de sesión de cámara.

Garantías de acceso exclusivo (M03):
  - Un único recurso de captura abierto (MAX_CONCURRENT_CAMERAS = 1).
  - Un único cliente activo (MAX_CONCURRENT_CLIENTS = 1).
  - Un segundo cliente recibe SessionBusyError sin tocar la sesión activa.
  - El escaneo de cámaras nunca abre la fuente que está en uso.

Ciclo de vida de la sesión (M07):

    idle ──start()──────────────▶ running ──connect_client()──▶ streaming
      ▲                              │  ▲                            │
      │                              │  └──── disconnect_client() ───┘
      └──────────── stop() ──────────┘        (sesión iniciada por operador)

  - Un cliente que se conecta con la sesión en `idle` la inicia por sí mismo
    (started_by = "client"). Al irse ese cliente, la cámara se cierra sola,
    porque nadie pidió mantenerla abierta.
  - Una sesión iniciada con start() (started_by = "operator") sigue abierta
    en `running` cuando el cliente se va, lista para el siguiente.
  - Mientras la cámara se cierra, el estado es `stopping`: el hardware puede
    tardar varios cientos de milisegundos en liberarse y nadie puede abrirla
    hasta que termine.
  - Cualquier operación fuera de orden lanza un SessionError con un código
    estable que los routers traducen a una respuesta controlada.
  - shutdown() es idempotente: libera lo que haya, deja de aceptar sesiones
    nuevas y registra el evento cada vez que se invoca.

Concurrencia: toda transición ocurre dentro de `_lock`. Las lecturas de frames
usan además un candado propio de la sesión (`io_lock`), de modo que el cierre
espera a que termine la lectura en curso antes de liberar el dispositivo.

Cada operación se ejecuta en una tarea propia del gestor (`_run_detached`).
Si quien la pidió se cancela (un cliente que se desconecta, un servidor que se
apaga), la operación termina igual y el candado se suelta solo cuando el
hardware quedó en un estado consistente. Esto es necesario porque anyio, que
usan Starlette y FastAPI, repite la cancelación en cada `await` del código
cancelado: esperar dentro de la tarea cancelada no basta.

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
    LIFECYCLE_EVENT_HISTORY,
    MAX_ERROR_HISTORY,
)
from app.services.camera_service import CameraCapture, open_camera

logger = logging.getLogger(__name__)


# ── Estado ────────────────────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    STREAMING = "streaming"
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
class CameraSession:
    camera_id: str
    capture: CameraCapture
    status: SessionStatus = SessionStatus.STREAMING
    active_client: Optional[str] = None
    started_by: StartedBy = StartedBy.CLIENT
    last_frame: Optional[np.ndarray] = None
    last_frame_ts: float = 0.0
    metrics: SessionMetrics = field(default_factory=SessionMetrics)
    errors: deque = field(
        default_factory=lambda: deque(maxlen=MAX_ERROR_HISTORY),
        repr=False,
    )
    # Serializa lecturas y cierre: nunca se libera la captura a mitad de una lectura
    io_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    closed: bool = False

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
            "started_by": self.started_by.value,
            "last_frame_ts": self.last_frame_ts or None,
            "metrics": self.metrics.to_dict(),
            "errors": [
                {"timestamp": e.timestamp, "message": e.message}
                for e in self.errors
            ],
        }


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


# ── Gestor ────────────────────────────────────────────────────────────────────

class CameraSessionManager:
    """
    Singleton que gestiona la única sesión de cámara y su ciclo de vida.

    Operaciones públicas:
      start / stop                       — administración explícita de la sesión
      connect_client / disconnect_client — entrada y salida del único cliente
      force_disconnect                   — expulsión del cliente por un operador
      read_frame                         — lectura segura para el cliente activo
      shutdown                           — apagado global idempotente
      get_status                         — estado y eventos del ciclo de vida

    acquire / release se conservan como alias de connect_client /
    disconnect_client por compatibilidad con el código y las pruebas de M02/M03.
    """

    def __init__(self) -> None:
        self._session: Optional[CameraSession] = None
        self._lock = asyncio.Lock()
        self._events: deque[LifecycleRecord] = deque(maxlen=LIFECYCLE_EVENT_HISTORY)
        # Clientes cuya sesión terminó por una acción externa → causa a comunicarles
        self._ended_clients: dict[str, str] = {}
        self._accepting = True
        # Número consecutivo de eventos: ordena sin depender de la resolución del reloj
        self._seq = 0
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
    def state(self) -> SessionStatus:
        """Estado del ciclo de vida, independiente de la salud de la sesión."""
        if self._session is None:
            if self._stopping_camera is not None:
                return SessionStatus.STOPPING
            return SessionStatus.IDLE
        if self._session.active_client is not None:
            return SessionStatus.STREAMING
        return SessionStatus.RUNNING

    @property
    def is_accepting(self) -> bool:
        return self._accepting

    def get_status(self) -> dict:
        """Estado serializable de la sesión actual y su historial de eventos."""
        if self._session is None:
            status = {"status": SessionStatus.IDLE.value, "active_client": None}
            if self._stopping_camera is not None:
                status["camera_id"] = self._stopping_camera
        else:
            status = self._session.to_dict()
        status["state"] = self.state.value
        status["accepting_clients"] = self._accepting
        status["events"] = [record.to_dict() for record in self._events]
        return status

    # ── Ejecución de hardware ────────────────────────────────────────────────

    async def _run_blocking(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_orphan: Optional[Callable[[Any], None]] = None,
    ) -> Any:
        """
        Ejecuta una operación bloqueante de hardware en un hilo.

        Si la tarea que espera se cancela, el hilo sigue trabajando. Por eso,
        antes de dejar salir la cancelación (y con ella soltar el candado), se
        espera a que el hilo termine. Si produjo un recurso que ya nadie va a
        usar, `on_orphan` se encarga de cerrarlo.
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

    # ── Transiciones internas (requieren `_lock` tomado) ─────────────────────

    def _record(
        self,
        event: LifecycleEvent,
        *,
        camera_id: Optional[str] = None,
        client_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
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
            status=SessionStatus.RUNNING,
            started_by=started_by,
            metrics=SessionMetrics(started_at=time.monotonic()),
        )
        self._record(LifecycleEvent.STARTED, camera_id=camera_id, reason=started_by.value)
        return self._session

    def _detach_client(self, session: CameraSession, reason: str, client_code: Optional[str]) -> None:
        client_id = session.active_client
        session.active_client = None
        if session.status == SessionStatus.STREAMING:
            session.status = SessionStatus.RUNNING
        if client_code is not None:
            self._ended_clients[client_id] = client_code
        self._record(
            LifecycleEvent.CLIENT_DISCONNECTED,
            camera_id=session.camera_id,
            client_id=client_id,
            reason=reason,
        )

    async def _close_session(self, reason: str, client_code: str) -> None:
        session = self._session
        if session.active_client is not None:
            self._detach_client(session, reason, client_code)
        # La sesión se retira antes de cerrar: aunque el driver falle, el recurso
        # no queda secuestrado. `_lock` sigue tomado, así nadie abre mientras tanto.
        session.closed = True
        self._session = None
        self._stopping_camera = session.camera_id
        try:
            await self._release_after_reads(session)
        finally:
            self._stopping_camera = None
        self._record(LifecycleEvent.STOPPED, camera_id=session.camera_id, reason=reason)

    async def _release_after_reads(self, session: CameraSession) -> None:
        async with session.io_lock:  # espera la lectura en curso, si la hay
            await self._run_blocking(_release_quietly, session.capture)

    # ── Ejecución desacoplada ────────────────────────────────────────────────

    async def _run_detached(
        self, coro: Awaitable[Any], request: Optional[_Request] = None
    ) -> Any:
        """
        Ejecuta la operación en una tarea propia y espera su resultado.

        Si quien espera se cancela, la tarea sigue hasta terminar (y conserva
        los candados mientras tanto). `request.abandoned` le avisa que nadie
        recibirá el resultado, para que deshaga lo que ya no tiene dueño.
        """
        task = asyncio.ensure_future(coro)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if request is not None:
                request.abandoned = True
            raise

    # ── Operaciones públicas ─────────────────────────────────────────────────

    async def start(
        self, camera_id: str, started_by: StartedBy = StartedBy.OPERATOR
    ) -> CameraSession:
        """
        Abre la cámara y deja la sesión en `running`, sin cliente.

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
                    f"Ya hay una sesión activa con la cámara '{self._session.camera_id}'."
                )
            return await self._open_session(camera_id, started_by)

    async def stop(self, reason: str = "operator") -> None:
        """
        Cierra la sesión. Si hay un cliente conectado, se le notifica con
        SESSION_STOPPED en su siguiente lectura.

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

        Si el cliente se cancela mientras espera, la conexión no se completa:
        se deshace dentro del mismo candado, sin dejar la cámara asignada a
        alguien que ya no existe.

        Raises:
            SessionBusyError: ya hay un cliente activo.
            CameraMismatchError: la sesión activa usa otra cámara.
            SessionCameraError: la fuente no pudo abrirse.
            ServiceShuttingDownError: el servicio se está apagando.
        """
        request = _Request()
        return await self._run_detached(
            self._connect_client(camera_id, client_id, request), request
        )

    async def _connect_client(
        self, camera_id: str, client_id: str, request: _Request
    ) -> Optional[CameraSession]:
        async with self._lock:
            if request.abandoned:
                return None
            self._ensure_accepting()
            session = self._session
            opened_here = False
            if session is None:
                session = await self._open_session(camera_id, StartedBy.CLIENT)
                opened_here = True
            elif session.active_client is not None:
                raise SessionBusyError(
                    "La cámara ya está en uso por otro cliente. "
                    "Solo se permite un cliente activo a la vez."
                )
            elif session.camera_id != camera_id:
                raise CameraMismatchError(
                    f"La sesión activa usa la cámara '{session.camera_id}', "
                    f"no '{camera_id}'."
                )

            if request.abandoned:
                # El cliente se fue mientras se abría la cámara
                if opened_here:
                    await self._close_session("abandoned", client_code="SESSION_STOPPED")
                return None

            session.active_client = client_id
            if session.status != SessionStatus.ERROR:
                session.status = SessionStatus.STREAMING
            self._ended_clients.pop(client_id, None)
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
            self._ended_clients.pop(client_id, None)
            session = self._session
            if session is None or session.active_client != client_id:
                return False
            self._detach_client(session, reason, client_code=None)
            if session.started_by == StartedBy.CLIENT:
                await self._close_session("auto_stop", client_code="SESSION_STOPPED")
            return True

    async def force_disconnect(self) -> str:
        """
        Expulsa al cliente activo por decisión de un operador.

        El cliente recibe CLIENT_DISCONNECTED en su siguiente lectura. Si la
        sesión la había iniciado el cliente, la cámara también se cierra.

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
            if session.started_by == StartedBy.CLIENT:
                await self._close_session("auto_stop", client_code="SESSION_STOPPED")
            return client_id

    async def read_frame(self, client_id: str) -> Optional[np.ndarray]:
        """
        Lee un frame para el cliente activo.

        Raises:
            ClientSessionEndedError: la sesión del cliente terminó por una
                acción externa; `code` indica la causa.
        """
        session = self._session
        if session is None or session.active_client != client_id:
            raise self._ended_error(client_id)
        return await self._run_detached(self._read_frame(session, client_id))

    async def _read_frame(self, session: CameraSession, client_id: str) -> Optional[np.ndarray]:
        async with session.io_lock:
            if session.closed or session.active_client != client_id:
                raise self._ended_error(client_id)
            frame = await self._run_blocking(session.capture.read_frame)
        session.update_frame(frame)
        return frame

    def _ended_error(self, client_id: str) -> ClientSessionEndedError:
        return ClientSessionEndedError(self._ended_clients.pop(client_id, "SESSION_STOPPED"))

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

    # ── Compatibilidad con M02/M03 ───────────────────────────────────────────

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
            self._ended_clients.clear()
            self._seq = 0


# Instancia global consumida por los routers
camera_session_manager = CameraSessionManager()
