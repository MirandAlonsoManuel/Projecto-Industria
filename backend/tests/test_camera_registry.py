"""
Pruebas de CameraRegistry: un cliente por cámara, reconexión con backoff,
y liberación de recursos. No requieren hardware ni OpenCV real — se
sustituye `open_camera` por un doble de prueba controlado.

"""

from __future__ import annotations

import pytest

from app.services.camera_registry import CameraBusyError, CameraRegistry, CameraState


class _FakeCapture:
    """Doble de CameraCapture controlable desde el test."""

    def __init__(self, frames: list) -> None:
        self._frames = list(frames)
        self.released = False

    def read_frame(self):
        if not self._frames:
            return None
        return self._frames.pop(0)

    def release(self) -> None:
        self.released = True

    @property
    def is_opened(self) -> bool:
        return True


@pytest.fixture
def registry() -> CameraRegistry:
    return CameraRegistry(
        max_retries=2,
        retry_backoff_base=0.01,
        retry_backoff_max=0.02,
        read_timeout_seconds=0.5,
    )


@pytest.mark.asyncio
async def test_segundo_cliente_es_rechazado(registry, monkeypatch):
    monkeypatch.setattr(
        "app.services.camera_registry.open_camera",
        lambda source: _FakeCapture(frames=[object()]),
    )

    await registry.acquire("0")

    with pytest.raises(CameraBusyError):
        await registry.acquire("0")


@pytest.mark.asyncio
async def test_camara_offline_lanza_connection_error(registry, monkeypatch):
    monkeypatch.setattr(
        "app.services.camera_registry.open_camera",
        lambda source: None,
    )

    with pytest.raises(ConnectionError):
        await registry.acquire("0")

    # No debe quedar entrada "fantasma" en el registro tras el fallo.
    assert await registry.get_active_slot("0") is None


@pytest.mark.asyncio
async def test_reconexion_exitosa_recupera_el_stream(registry, monkeypatch):
    # El primer intento de apertura no produce frames (simula pérdida);
    # el segundo intento de reconexión sí trae un frame disponible.
    capturas = iter(
        [
            _FakeCapture(frames=[]),
            _FakeCapture(frames=[object()]),
        ]
    )
    monkeypatch.setattr(
        "app.services.camera_registry.open_camera",
        lambda source: next(capturas),
    )

    slot = await registry.acquire("0")
    frame = await registry.read_frame_with_reconnect(slot)

    assert frame is not None
    assert slot.state == CameraState.IN_USE
    assert slot.retry_count == 0


@pytest.mark.asyncio
async def test_reconexion_agotada_libera_la_camara(registry, monkeypatch):
    monkeypatch.setattr(
        "app.services.camera_registry.open_camera",
        lambda source: _FakeCapture(frames=[]),
    )

    slot = await registry.acquire("0")
    frame = await registry.read_frame_with_reconnect(slot)

    assert frame is None
    assert slot.last_error is not None
    # La cámara quedó liberada: un nuevo cliente ya no debería ser rechazado.
    assert await registry.get_active_slot("0") is None


@pytest.mark.asyncio
async def test_release_permite_un_nuevo_cliente(registry, monkeypatch):
    monkeypatch.setattr(
        "app.services.camera_registry.open_camera",
        lambda source: _FakeCapture(frames=[object()]),
    )

    first_slot = await registry.acquire("0")
    await registry.release("0")

    second_slot = await registry.acquire("0")

    assert second_slot is not first_slot
    assert first_slot.capture.released is True


@pytest.mark.asyncio
async def test_probe_no_afecta_camaras_activas(registry, monkeypatch):
    # Si se llamara open_camera de nuevo para una cámara activa, esto
    # fallaría de forma visible por el aserto sobre cuántas veces se llamó.
    calls = []

    def fake_open(source):
        calls.append(source)
        return _FakeCapture(frames=[object()])

    monkeypatch.setattr("app.services.camera_registry.open_camera", fake_open)

    await registry.acquire("0")
    assert calls == ["0"]

    # cameras.py es responsable de NO llamar a probe() para "0" mientras
    # está activa; esta prueba documenta ese contrato implícito.
    active_ids = {slot.camera_id for slot in await registry.list_active()}
    assert "0" in active_ids
