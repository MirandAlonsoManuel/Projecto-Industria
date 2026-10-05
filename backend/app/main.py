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
from app.services.inference_engine import SimulatedInferenceEngine
from app.services.inference_lifecycle import InferenceEngineLifecycle


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida de la aplicación.

    [SUPUESTO] El motor conectado aquí es `SimulatedInferenceEngine`
    (E01/E02 no integran todavía un motor real — ver
    docs/E02_inference_lifecycle_contract.md, sección 5). Conectar un
    motor real es trabajo de una tarea posterior.

    [SUPUESTO] Si `lifecycle.initialize()` falla, la excepción se deja
    propagar: el arranque de la aplicación falla por completo (FastAPI
    nunca llega a aceptar tráfico) en vez de iniciar en un modo
    degradado. Es la opción más simple y seguridad por defecto; si el
    equipo prefiere que la app arranque igual y solo el estado quede en
    `ERROR` (modo degradado), es una decisión de producto a confirmar
    con el líder técnico, no algo que este ticket decida unilateralmente.

    Si el líder técnico ya definió, en otra rama, un lifespan propio
    para base de datos y/o cámaras, ambos deben fusionarse aquí —
    FastAPI solo admite un lifespan por aplicación.
    """
    lifecycle = InferenceEngineLifecycle(SimulatedInferenceEngine())
    app.state.inference_lifecycle = lifecycle

    await lifecycle.initialize()
    try:
        yield
    finally:
        await lifecycle.shutdown()


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
