"""Pruebas de aceptación del diseño M01 sin cámara física."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import patch

import numpy as np
import pytest

from app.services.camera_session_manager import (
    CameraSessionManager,
    SessionBusyError,
    SessionCameraError,
    SessionStatus,
)


@dataclass
class CaptureStats:
    opens: int = 0
    releases: int = 0
    active: int = 0
    max_active: int = 0


class FakeCapture:
    def __init__(self, stats: CaptureStats) -> None:
        self._stats = stats
        self._released = False
        stats.opens += 1
        stats.active += 1
        stats.max_active = max(stats.max_active, stats.active)

    @property
    def is_opened(self) -> bool:
        return not self._released

    def read_frame(self) -> np.ndarray:
        return np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._stats.releases += 1
        self._stats.active -= 1


def run(coro):
    return asyncio.run(coro)


def test_idle_streaming_idle_con_un_solo_propietario():
    stats = CaptureStats()
    manager = CameraSessionManager()

    async def scenario():
        assert manager.get_status() == {"status": "idle", "active_client": None}
        with patch(
            "app.services.camera_session_manager.open_camera",
            side_effect=lambda _: FakeCapture(stats),
        ):
            session = await manager.acquire("0", "cliente-1")
            assert session.status is SessionStatus.STREAMING
            assert manager.get_status()["active_client"] == "cliente-1"
            assert await manager.release("cliente-1") is True
        assert manager.get_status() == {"status": "idle", "active_client": None}

    run(scenario())

    assert stats.opens == 1
    assert stats.releases == 1
    assert stats.active == 0


def test_segundo_cliente_se_rechaza_sin_otra_apertura():
    stats = CaptureStats()
    manager = CameraSessionManager()

    async def scenario():
        with patch(
            "app.services.camera_session_manager.open_camera",
            side_effect=lambda _: FakeCapture(stats),
        ):
            first = await manager.acquire("0", "cliente-1")
            with pytest.raises(SessionBusyError) as error:
                await manager.acquire("0", "cliente-2")
            assert error.value.code == "CAMERA_BUSY"
            assert manager.session is first
            assert manager.session.active_client == "cliente-1"
            await manager.release("cliente-1")

    run(scenario())

    assert stats.opens == 1
    assert stats.max_active == 1


def test_cliente_no_propietario_no_puede_liberar():
    stats = CaptureStats()
    manager = CameraSessionManager()

    async def scenario():
        with patch(
            "app.services.camera_session_manager.open_camera",
            side_effect=lambda _: FakeCapture(stats),
        ):
            session = await manager.acquire("0", "propietario")
            assert await manager.release("otro-cliente") is False
            assert manager.session is session
            assert stats.releases == 0
            await manager.release("propietario")

    run(scenario())
    assert stats.releases == 1


def test_fallo_de_apertura_no_publica_sesion_parcial():
    manager = CameraSessionManager()

    async def scenario():
        with patch("app.services.camera_session_manager.open_camera", return_value=None):
            with pytest.raises(SessionCameraError) as error:
                await manager.acquire("0", "cliente-1")
        assert error.value.code == "CAMERA_UNAVAILABLE"
        assert manager.session is None
        assert manager.get_status()["status"] == "idle"

    run(scenario())


def test_error_conserva_causa_hasta_liberar_y_permita_reconexion():
    stats = CaptureStats()
    manager = CameraSessionManager()

    async def scenario():
        with patch(
            "app.services.camera_session_manager.open_camera",
            side_effect=lambda _: FakeCapture(stats),
        ):
            session = await manager.acquire("0", "cliente-1")
            session.record_error("lectura interrumpida")

            status = manager.get_status()
            assert status["status"] == "error"
            assert status["errors"][-1]["message"] == "lectura interrumpida"

            await manager.release("cliente-1")
            replacement = await manager.acquire("0", "cliente-2")
            assert replacement.status is SessionStatus.STREAMING
            assert len(replacement.errors) == 0
            await manager.release("cliente-2")

    run(scenario())

    assert stats.opens == 2
    assert stats.releases == 2
    assert stats.max_active == 1


def test_ultimo_frame_y_metricas_pertenecen_a_la_sesion():
    stats = CaptureStats()
    manager = CameraSessionManager()
    frame = np.ones((4, 4, 3), dtype=np.uint8)

    async def scenario():
        with patch(
            "app.services.camera_session_manager.open_camera",
            side_effect=lambda _: FakeCapture(stats),
        ):
            session = await manager.acquire("0", "cliente-1")
            session.update_frame(frame)
            session.update_frame(None)

            status = manager.get_status()
            assert session.last_frame is frame
            assert status["last_frame_ts"] is not None
            assert status["metrics"]["frames_total"] == 1
            assert status["metrics"]["frames_dropped"] == 1

            await manager.release("cliente-1")
            assert manager.get_status()["status"] == "idle"

    run(scenario())


def test_clientes_concurrentes_no_duplican_captura():
    stats = CaptureStats()
    manager = CameraSessionManager()

    async def scenario():
        with patch(
            "app.services.camera_session_manager.open_camera",
            side_effect=lambda _: FakeCapture(stats),
        ):
            results = await asyncio.gather(
                *(manager.acquire("0", f"cliente-{index}") for index in range(12)),
                return_exceptions=True,
            )
            accepted = [result for result in results if not isinstance(result, Exception)]
            busy = [result for result in results if isinstance(result, SessionBusyError)]
            assert len(accepted) == 1
            assert len(busy) == 11
            await manager.release(accepted[0].active_client)

    run(scenario())

    assert stats.opens == 1
    assert stats.releases == 1
    assert stats.max_active == 1
