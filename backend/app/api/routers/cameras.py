"""
Router REST para gestión y consulta de fuentes de video (cámaras).

Todos los endpoints siguen la estructura de respuesta uniforme:
  { "data": ..., "error": null | string, "meta": { ... } }
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.services.camera_service import detect_available_cameras
from app.services.camera_session_manager import camera_session_manager

router = APIRouter(tags=["cameras"])


@router.get(
    "/cameras",
    summary="Listar cámaras disponibles en el dispositivo",
    description=(
        "Escanea los índices USB del dispositivo y retorna las cámaras "
        "que responden correctamente. Si no se detecta ninguna, `connected` "
        "será `false` y `data` estará vacío."
    ),
)
async def list_cameras() -> JSONResponse:
    """
    Retorna las cámaras detectadas en el dispositivo.

    **Códigos de respuesta:**
    - `200 OK` — escaneo completado (puede retornar lista vacía si no hay cámaras).
    """
    loop = asyncio.get_event_loop()
    cameras: list[dict] = await loop.run_in_executor(
        None, detect_available_cameras
    )

    connected = len(cameras) > 0
    description = (
        f"Se detectaron {len(cameras)} cámara(s) en el dispositivo."
        if connected
        else "No se detectaron cámaras en el dispositivo."
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "connected": connected,
            "data": cameras,
            "error": None,
            "meta": {
                "total": len(cameras),
                "description": description,
            },
        },
    )


@router.get(
    "/cameras/session",
    summary="Estado de la sesión de cámara activa",
    description=(
        "Retorna el estado actual del gestor de sesiones: cámara activa, "
        "cliente conectado, métricas de captura y registro de errores. "
        "Si no hay sesión activa, `status` es `idle`."
    ),
)
def session_status() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=camera_session_manager.get_status(),
    )
