"""
Router REST para gestión y consulta de fuentes de video (cámaras).

Incluye las operaciones de operador sobre el ciclo de vida de la sesión (M07):
iniciar, detener y desconectar al cliente. El frontend no necesita usarlas:
conectarse al WebSocket sigue iniciando la sesión por sí solo.

Los endpoints de listado y de operaciones siguen la estructura uniforme:
  { "data": ..., "error": null | código, "meta": { "description": ... } }
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.services.camera_service import detect_available_cameras
from app.services.camera_session_manager import SessionError, camera_session_manager
from app.services.redaction import redact_source

router = APIRouter(tags=["cameras"])


def _ok(data: Any, description: str, status_code: int = status.HTTP_200_OK) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": data, "error": None, "meta": {"description": description}},
    )


def _session_error(exc: SessionError) -> JSONResponse:
    """Traduce una transición inválida a una respuesta controlada."""
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "data": camera_session_manager.get_lifecycle_status(),
            "error": exc.code,
            "meta": {"description": str(exc)},
        },
    )


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
    que ya está en uso (acceso exclusivo, M03).

    **Códigos de respuesta:**
    - `200 OK` — escaneo completado (puede retornar lista vacía si no hay cámaras).
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
    summary="Estado de la sesión de cámara",
    description=(
        "Retorna el estado del ciclo de vida (`idle`, `running`, `stopping` o "
        "`streaming`), quién inició la sesión, el cliente conectado, métricas, "
        "errores y el historial de eventos con su número consecutivo `seq`."
    ),
)
def session_status() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=camera_session_manager.get_lifecycle_status(),
    )


@router.get(
    "/cameras/metrics",
    summary="Métricas operativas de la cámara y el streaming",
    description=(
        "Reúne en una sola consulta el estado de la cámara, el único cliente "
        "(`connected` vale 0 o 1), los frames capturados, perdidos, enviados y "
        "saltados, las recuperaciones, los errores y el último error. Cada "
        "contador se reporta para la sesión actual (`session`) y acumulado "
        "desde que arrancó el servicio (`since_start`). Ningún campo contiene "
        "credenciales: las fuentes RTSP se muestran enmascaradas."
    ),
)
def camera_metrics() -> JSONResponse:
    return _ok(camera_session_manager.get_metrics(), "Métricas operativas de la cámara.")


@router.post(
    "/cameras/session/start",
    summary="Iniciar la sesión de cámara",
    description=(
        "Abre la cámara y deja la sesión en `running`, lista para un cliente. "
        "Al desconectarse ese cliente, la cámara sigue abierta."
    ),
    responses={
        409: {"description": "SESSION_ALREADY_ACTIVE — ya hay una sesión iniciada."},
        503: {"description": "CAMERA_UNAVAILABLE o SERVICE_SHUTTING_DOWN."},
    },
)
async def start_session(
    camera_id: str = Query(
        default="0",
        description="Índice USB (0, 1, …), URL rtsp:// o ruta a archivo de video.",
    ),
) -> JSONResponse:
    try:
        await camera_session_manager.start(camera_id)
    except SessionError as exc:
        return _session_error(exc)
    return _ok(
        camera_session_manager.get_lifecycle_status(),
        f"Sesión iniciada con la cámara '{redact_source(camera_id)}'.",
        status_code=status.HTTP_201_CREATED,
    )


@router.post(
    "/cameras/session/stop",
    summary="Detener la sesión de cámara",
    description=(
        "Cierra la cámara. Si hay un cliente conectado, recibe "
        "`SESSION_STOPPED` y su WebSocket se cierra con 1000."
    ),
    responses={409: {"description": "SESSION_NOT_ACTIVE — no hay sesión que detener."}},
)
async def stop_session() -> JSONResponse:
    try:
        await camera_session_manager.stop()
    except SessionError as exc:
        return _session_error(exc)
    return _ok(camera_session_manager.get_lifecycle_status(), "Sesión detenida.")


@router.post(
    "/cameras/session/disconnect",
    summary="Desconectar al cliente activo",
    description=(
        "Cierra la conexión del cliente con `CLIENT_DISCONNECTED`. Si la sesión "
        "la inició un operador, la cámara sigue abierta en `running`; si la "
        "inició el propio cliente, también se cierra."
    ),
    responses={409: {"description": "NO_CLIENT_CONNECTED — no hay cliente conectado."}},
)
async def disconnect_client() -> JSONResponse:
    try:
        client_id = await camera_session_manager.force_disconnect()
    except SessionError as exc:
        return _session_error(exc)
    return _ok(
        {"client_id": client_id, **camera_session_manager.get_lifecycle_status()},
        f"Cliente '{client_id}' desconectado.",
    )
