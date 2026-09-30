"""
Pruebas de humo de infraestructura (E00).

Validan que la aplicación se puede construir y responder sin cámara
física, sin modelo real y sin acceso a la red: se usa httpx.AsyncClient
contra la app en memoria (ASGITransport), nunca se levanta un servidor
real ni se abre un socket de verdad.
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


def test_create_app_no_lanza_excepciones() -> None:
    """create_app() debe devolver una instancia de FastAPI sin fallar.

    Sirve como red de seguridad básica: si algún router tiene un import
    roto (p. ej. un módulo que ya no existe tras un cambio), esta prueba
    falla aquí en vez de descubrirse manualmente al levantar uvicorn.
    """
    app = create_app()
    assert isinstance(app, FastAPI)


async def test_signal_responde_conectado() -> None:
    """GET /signal debe confirmar que la API está en línea."""
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/signal")

    assert response.status_code == 200
    assert response.json() == {"connected": True}


def test_settings_se_sobrescriben_por_variable_de_entorno(monkeypatch) -> None:
    """
    pydantic-settings debe leer JPEG_QUALITY del entorno y sobrescribir
    el valor por defecto de Settings.jpeg_quality (ver app/core/config.py).
    """
    monkeypatch.setenv("JPEG_QUALITY", "42")
    get_settings.cache_clear()  # redundante con el fixture autouse, explícito a propósito

    settings = get_settings()

    assert settings.jpeg_quality == 42
