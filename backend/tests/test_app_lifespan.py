"""
Prueba de integración (E02): confirma que la aplicación completa puede
arrancar y detenerse usando el ciclo de vida del motor simulado,
enganchado al lifespan de FastAPI en app/main.py — sin modelo real ni
cámara física, y sin modificar ningún otro router.
"""

from __future__ import annotations

import pytest

from app.main import create_app
from app.services.inference_lifecycle import LifecycleState


@pytest.mark.asyncio
async def test_lifespan_inicializa_y_cierra_el_motor_simulado():
    app = create_app()

    async with app.router.lifespan_context(app):
        lifecycle = app.state.inference_lifecycle
        status = lifecycle.get_status()
        assert status.state == LifecycleState.AVAILABLE
        assert status.loaded_at is not None

    # Al salir del context manager, Starlette disparó el evento de cierre.
    assert lifecycle.get_status().state == LifecycleState.CLOSED
