"""
Fixtures compartidas para la suite de pruebas del backend.

[E00] Infraestructura de pruebas aisladas: ninguna prueba de este árbol
debe abrir una cámara física, cargar un modelo real, ni acceder a la red.
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """
    Limpia el caché de `get_settings()` antes y después de cada prueba.

    `get_settings` está decorado con `@lru_cache` (ver app/core/config.py),
    así que una vez resuelto queda fijo durante todo el proceso. Sin este
    fixture, una prueba que sobrescribe una variable de entorno con
    `monkeypatch.setenv(...)` podría ver el valor cacheado de una prueba
    anterior en vez del suyo — o, peor, contaminar las pruebas que corran
    después de ella. Al ser `autouse=True`, se aplica a toda la suite sin
    que cada test tenga que pedirlo explícitamente.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
