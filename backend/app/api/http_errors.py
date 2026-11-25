"""
Traducción de excepciones del dominio a respuestas HTTP (BUG-09 y BUG-19, KIKE-8).

Regla de oro: el cliente solo recibe mensajes que NOSOTROS escribimos para él.

- Errores del cliente (imagen inválida, ROI inválida, modelo inexistente, tareas
  que no coinciden, tamaños distintos): 400 con el mensaje, porque describe qué
  corregir y está redactado sin datos internos.
- Errores del servidor (fallo al cargar o ejecutar un modelo, configuración
  rota, cualquier excepción inesperada): 503/500 con un mensaje GENÉRICO. El
  detalle real (que puede incluir rutas del disco, versiones de CUDA/torch o
  trazas) se registra solo en el log del servidor.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app.services.image_service import ImageInputError
from app.services.inference_service import InferenceError, InferenceRequestError
from app.services.model_registry import ModelRegistryError

logger = logging.getLogger("uvicorn.error")

SERVICE_UNAVAILABLE_DETAIL = (
    "El servicio de inferencia no está disponible en este momento. "
    "Intente de nuevo más tarde."
)
INTERNAL_ERROR_DETAIL = "Error interno del servidor."


def to_http_error(exc: Exception) -> HTTPException:
    # Errores atribuibles a lo que envió el cliente: 400 con el mensaje.
    if isinstance(exc, (ImageInputError, ModelRegistryError, InferenceRequestError)):
        return HTTPException(status_code=400, detail=str(exc))

    # Errores del servidor: detalle al log, mensaje genérico al cliente.
    # `logger.error(..., exc_info=exc)` guarda también la causa encadenada.
    if isinstance(exc, InferenceError):
        logger.error("Fallo del servicio de inferencia: %s", exc, exc_info=exc)
        return HTTPException(status_code=503, detail=SERVICE_UNAVAILABLE_DETAIL)

    logger.error("Error inesperado al procesar la petición: %s", exc, exc_info=exc)
    return HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL)
