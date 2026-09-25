"""
Punto de entrada principal de la aplicación.

Inicializa la instancia de FastAPI con la configuración del proyecto
y registra todos los routers disponibles.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.routers import health, inference
from app.api.routers import stream, cameras
from app.services.camera_registry import get_camera_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida de la aplicación.

    [SUPUESTO] Este lifespan solo cubre el cierre ordenado del registro de
    cámaras (requisito propio de esta línea de trabajo: ninguna sesión ni
    dispositivo debe quedar abierto al apagar la app). Si el líder técnico
    ya definió, en otra rama, un lifespan propio para base de datos y/o
    modelo de inferencia, ambos deben fusionarse aquí — FastAPI solo
    admite un lifespan por aplicación.
    """
    yield
    await get_camera_registry().shutdown_all()


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
