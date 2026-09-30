
from __future__ import annotations

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
        "que responden correctamente. La cámara que esté transmitiendo se "
        "reporta con `status: in_use` sin volver a abrirla. Si no se detecta "
        "ninguna, `connected` será `false` y `data` estará vacío."
    ),
)
async def list_cameras() -> JSONResponse:
    """
    Retorna las cámaras detectadas en el dispositivo.

    El escaneo pasa por el gestor de sesión para que nunca abra la cámara
    que ya está en uso (acceso exclusivo).
    """
    cameras = await camera_session_manager.scan_cameras(detect_available_cameras)

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
