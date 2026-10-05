"""
Slot de último frame: punto de desacople entre captura y consumidores.

La captura publica aquí cada frame completo y sobrescribe el anterior. No hay
cola: un consumidor lento nunca acumula retraso, simplemente se salta los
frames intermedios y recibe el más reciente.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class FramePacket:
    seq: int
    frame: np.ndarray
    captured_at: float


class FrameSlotClosed(Exception):
    """El slot ya no recibirá más frames."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.code = code


class FrameSlot:
    """Buffer de tamaño 1 con número de secuencia y espera asíncrona."""

    def __init__(self) -> None:
        self._packet: Optional[FramePacket] = None
        self._seq = 0
        self._closed_reason: Optional[str] = None
        self._closed_code = ""
        self._event = asyncio.Event()

    @property
    def latest(self) -> Optional[FramePacket]:
        return self._packet

    @property
    def closed(self) -> bool:
        return self._closed_reason is not None

    def publish(self, frame: np.ndarray, captured_at: float) -> FramePacket:
        """Reemplaza el frame actual y despierta a los consumidores en espera."""
        self._seq += 1
        self._packet = FramePacket(seq=self._seq, frame=frame, captured_at=captured_at)
        self._event.set()
        return self._packet

    def close(self, reason: str, code: str = "STREAM_CLOSED") -> None:
        """Marca el fin de la captura; los consumidores reciben FrameSlotClosed."""
        if self._closed_reason is None:
            self._closed_reason = reason
            self._closed_code = code
        self._event.set()

    async def next(self, after_seq: int = 0) -> FramePacket:
        """
        Retorna el frame más reciente con secuencia mayor a `after_seq`.

        Raises:
            FrameSlotClosed: la captura terminó y no hay un frame más nuevo.
        """
        while True:
            packet = self._packet
            if packet is not None and packet.seq > after_seq:
                return packet
            if self._closed_reason is not None:
                raise FrameSlotClosed(self._closed_reason, self._closed_code)
            self._event.clear()
            await self._event.wait()
