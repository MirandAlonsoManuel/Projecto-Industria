"""
Punto de entrada principal de la aplicación.

Inicializa la instancia de FastAPI con la configuración del proyecto
y registra todos los routers disponibles.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.routers import health, inference
from app.api.routers import stream, cameras
from app.services.camera_session_manager import camera_session_manager

# Logger de uvicorn: sus mensajes aparecen en la consola del servidor
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida del proceso.

    Al apagarse el servidor se ejecuta el apagado global de la cámara: se
    libera la sesión si existe y se dejan de aceptar sesiones nuevas. La
    operación es idempotente, así que es seguro aunque la sesión ya esté cerrada.
    """
    yield
    released = await camera_session_manager.shutdown()
    logger.info(
        "Apagado global de cámara: %s",
        "sesión liberada" if released else "no había sesión activa",
    )


def create_app() -> FastAPI:
    """
    Construye y configura la aplicación FastAPI.

    Lee la configuración centralizada para establecer el título y la versión
    expuestos en la documentación automática (Swagger / ReDoc), luego registra
    cada router de la API.

    Returns:
        FastAPI: Instancia lista para ser servida por el servidor ASGI.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version_api,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rutas de diagnóstico y estado del servicio
    app.include_router(health.router)

    # Rutas de inferencia del modelo de machine learning
    app.include_router(inference.router)

    # Gestión de cámaras (REST) y streaming en tiempo real (WebSocket)
    app.include_router(cameras.router)
    app.include_router(stream.router)

    return app


# Instancia global consumida por el servidor ASGI (uvicorn app.main:app)
app = create_app()
