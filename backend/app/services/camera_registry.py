"""
Registro en memoria de sesiones de cámara.

Aplica la política de "un solo cliente por cámara", gestiona la
reconexión automática ante fallas de lectura, y expone el estado
consultable de cada fuente: offline, available, in_use, reconnecting.

"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Awaitable, Callable, Optional

from app.services.camera_service import CameraCapture, open_camera

logger = logging.getLogger(__name__)


class CameraState(str, Enum):
    OFFLINE = "offline"
    AVAILABLE = "available"
    IN_USE = "in_use"
    RECONNECTING = "reconnecting"


@dataclass
class CameraSlot:
    """Sesión activa (o en reconexión) de una cámara."""

    camera_id: str
    state: CameraState
    capture: Optional[CameraCapture] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    connected_since: Optional[float] = None


class CameraBusyError(Exception):
    """La cámara solicitada ya tiene un cliente conectado."""


OnStateChange = Callable[[CameraSlot], Awaitable[None]]


class CameraRegistry:
    """
    Registro central de sesiones de cámara. Garantiza apertura única por
    `camera_id`, rechaza un segundo cliente mientras la sesión esté activa,
    y coordina la reconexión con backoff cuando falla una lectura.
    """

    def __init__(
        self,
        max_retries: int,
        retry_backoff_base: float,
        retry_backoff_max: float,
        read_timeout_seconds: float,
    ) -> None:
        self._slots: dict[str, CameraSlot] = {}
        self._lock = asyncio.Lock()
        self._max_retries = max_retries
        self._retry_backoff_base = retry_backoff_base
        self._retry_backoff_max = retry_backoff_max
        self._read_timeout_seconds = read_timeout_seconds

    # ---- ciclo de vida de una sesión --------------------------------

    async def acquire(self, camera_id: str) -> CameraSlot:
        """
        Reserva `camera_id` para un nuevo cliente y abre la fuente.

        Raises:
            CameraBusyError: ya hay un cliente conectado a esa cámara.
            ConnectionError: la fuente no pudo abrirse.
        """
        loop = asyncio.get_event_loop()

        async with self._lock:
            existing = self._slots.get(camera_id)
            if existing is not None and existing.state in (
                CameraState.IN_USE,
                CameraState.RECONNECTING,
            ):
                raise CameraBusyError(camera_id)

            # Entrada provisional: cualquier acquire() concurrente para esta
            # misma cámara la verá ocupada de inmediato, aunque el hardware
            # todavía no haya terminado de abrirse (evita apertura doble).
            slot = CameraSlot(camera_id=camera_id, state=CameraState.IN_USE)
            self._slots[camera_id] = slot

        capture = await loop.run_in_executor(None, open_camera, camera_id)

        if capture is None:
            async with self._lock:
                # Solo removemos si sigue siendo nuestra propia entrada
                # provisional (por si algo más la reemplazó, defensivo).
                if self._slots.get(camera_id) is slot:
                    self._slots.pop(camera_id, None)
            raise ConnectionError(f"No se pudo abrir la cámara '{camera_id}'")

        slot.capture = capture
        slot.connected_since = time.time()
        return slot

    async def release(self, camera_id: str) -> None:
        """Libera el recurso físico y borra la entrada del registro."""
        loop = asyncio.get_event_loop()
        async with self._lock:
            slot = self._slots.pop(camera_id, None)

        if slot is None or slot.capture is None:
            return

        await loop.run_in_executor(None, slot.capture.release)

    # ---- lectura con reconexión ---------------------------------------

    async def read_frame_with_reconnect(
        self,
        slot: CameraSlot,
        on_state_change: Optional[OnStateChange] = None,
    ):
        """
        Lee el siguiente frame de `slot`. Si la lectura falla, intenta
        reconectar con backoff antes de rendirse.

        Devuelve el frame, o `None` si se agotaron los reintentos — en ese
        caso la sesión ya fue liberada (release()) antes de retornar.
        """
        loop = asyncio.get_event_loop()

        frame = await self._safe_read(loop, slot.capture)
        if frame is not None:
            if slot.state != CameraState.IN_USE:
                slot.state = CameraState.IN_USE
                slot.retry_count = 0
                if on_state_change:
                    await on_state_change(slot)
            return frame

        slot.state = CameraState.RECONNECTING
        if on_state_change:
            await on_state_change(slot)

        for attempt in range(1, self._max_retries + 1):
            slot.retry_count = attempt
            backoff = min(
                self._retry_backoff_base * (2 ** (attempt - 1)),
                self._retry_backoff_max,
            )
            await asyncio.sleep(backoff)

            if slot.capture is not None:
                await loop.run_in_executor(None, slot.capture.release)
                slot.capture = None

            new_capture = await loop.run_in_executor(
                None, open_camera, slot.camera_id
            )
            if new_capture is not None:
                slot.capture = new_capture
                frame = await self._safe_read(loop, slot.capture)
                if frame is not None:
                    slot.state = CameraState.IN_USE
                    slot.retry_count = 0
                    slot.last_error = None
                    if on_state_change:
                        await on_state_change(slot)
                    return frame

            slot.last_error = (
                f"Reintento {attempt}/{self._max_retries} fallido "
                f"para '{slot.camera_id}'"
            )
            logger.warning(slot.last_error)

        slot.last_error = (
            f"Se agotaron los {self._max_retries} reintentos "
            f"para '{slot.camera_id}'"
        )
        logger.error(slot.last_error)
        await self.release(slot.camera_id)
        return None

    async def _safe_read(self, loop, capture: Optional[CameraCapture]):
        if capture is None:
            return None
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, capture.read_frame),
                timeout=self._read_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return None

    # ---- consulta de estado ---------------------------------------------

    async def get_active_slot(self, camera_id: str) -> Optional[CameraSlot]:
        async with self._lock:
            return self._slots.get(camera_id)

    async def list_active(self) -> list[CameraSlot]:
        async with self._lock:
            return list(self._slots.values())

    async def probe(self, camera_id: str) -> CameraState:
        """
        Sondea una cámara SIN entrada activa en el registro (abre y libera
        de inmediato) para decidir entre AVAILABLE y OFFLINE.

        No debe llamarse para un `camera_id` que ya está en el registro —
        eso reabriría un dispositivo en uso. Quien llame (cameras.py) es
        responsable de filtrar por `list_active()` antes de invocar esto.
        """
        loop = asyncio.get_event_loop()
        capture = await loop.run_in_executor(None, open_camera, camera_id)
        if capture is None:
            return CameraState.OFFLINE
        await loop.run_in_executor(None, capture.release)
        return CameraState.AVAILABLE

    # ---- apagado global ---------------------------------------------------

    async def shutdown_all(self) -> None:
        """Cancela sesiones activas y libera todos los dispositivos abiertos."""
        async with self._lock:
            camera_ids = list(self._slots.keys())
        for camera_id in camera_ids:
            await self.release(camera_id)


@lru_cache
def get_camera_registry() -> CameraRegistry:
    """
    Retorna la instancia única del registro de cámaras.

    Sigue el mismo patrón singleton (`lru_cache`) que `get_settings()` en
    `app.core.config`, para mantener consistencia con el resto del proyecto.
    """
    # Import local para evitar un ciclo de imports entre config y registry.
    from app.core.config import get_settings

    settings = get_settings()
    return CameraRegistry(
        max_retries=settings.max_retries,
        retry_backoff_base=settings.retry_backoff_base,
        retry_backoff_max=settings.retry_backoff_max,
        read_timeout_seconds=settings.read_timeout_seconds,
    )
