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
from app.services.inference_lifecycle import inference_lifecycle

# Logger de uvicorn: sus mensajes aparecen en la consola del servidor
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Ciclo de vida del proceso.

    Arranque: inicializa el motor de inferencia (E02 — ver
    `inference_lifecycle.py`). Usa el singleton `inference_lifecycle`
    (mismo patrón que `camera_session_manager`: importable a nivel de
    módulo, no un objeto local oculto en `app.state`) para que cualquier
    consumidor futuro pueda acceder a él con un simple import.

    Apagado: cierra el motor de inferencia y realiza el apagado global
    de cámara (`camera_session_manager`). Cada cierre está protegido por
    separado para que un fallo en uno no impida que el otro se ejecute
    — ninguno de los dos debe dejar recursos a medio liberar por culpa
    del otro.

    [SUPUESTO] El motor conectado es `SimulatedInferenceEngine` (E01/E02
    no integran todavía un motor real — ver
    docs/E02_inference_lifecycle_contract.md, sección 5). Conectar un
    motor real es trabajo de una tarea posterior.

    [SUPUESTO] Si `inference_lifecycle.initialize()` falla, la excepción
    se deja propagar: el arranque de la aplicación falla por completo
    en vez de iniciar en modo degradado. Es una decisión de producto a
    confirmar con el líder técnico, no algo que este ticket decida
    unilateralmente. (El apagado de cámara no tiene un paso de arranque
    propio, así que esta decisión no lo afecta.)
    """
    await inference_lifecycle.initialize()
    # Se mantiene también en app.state por conveniencia (p. ej. para un
    # futuro endpoint de salud que necesite el objeto `app`/`Request`),
    # pero el singleton importado es la vía principal de acceso.
    app.state.inference_lifecycle = inference_lifecycle

    try:
        yield
    finally:
        try:
            await inference_lifecycle.shutdown()
        except Exception:
            logger.exception("Error cerrando el ciclo de vida de inferencia.")

        try:
            released = await camera_session_manager.shutdown()
            logger.info(
                "Apagado global de cámara: %s",
                "sesión liberada" if released else "no había sesión activa",
            )
        except Exception:
            logger.exception("Error en el apagado global de cámara.")


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
