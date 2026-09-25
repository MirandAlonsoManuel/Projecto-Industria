"""
Router REST para gestión y consulta de fuentes de video (cámaras).

Todos los endpoints siguen la estructura de respuesta uniforme:
  { "data": ..., "error": null | string, "meta": { ... } }

El listado combina dos fuentes sin que se pisen entre sí:
  1. Cámaras con sesión activa en el registro (in_use / reconnecting):
     se reporta el estado directo del registro, SIN volver a tocar el
     hardware (evita reabrir un dispositivo que ya está en uso).
  2. Índices USB sin sesión activa: se sondean (open + release rápido)
     para decidir entre available / offline.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.services.camera_registry import CameraSlot, CameraState, get_camera_registry

router = APIRouter(tags=["cameras"])


def _slot_to_dict(slot: CameraSlot) -> dict:
    return {
        "id": slot.camera_id,
        "type": "usb" if slot.camera_id.isdigit() else "network_or_file",
        "state": slot.state.value,
        "connected_since": slot.connected_since,
        "retry_count": slot.retry_count,
        "last_error": slot.last_error,
    }


@router.get(
    "/cameras",
    summary="Listar cámaras y su estado",
    description=(
        "Combina las sesiones activas del registro (in_use, reconnecting) "
        "con un sondeo de los índices USB sin sesión activa (available, "
        "offline). Fuentes RTSP o de archivo solo aparecen aquí una vez "
        "que algún cliente intentó conectarse a ellas."
    ),
)
async def list_cameras() -> JSONResponse:
    """
    Retorna las cámaras conocidas y su estado actual.

    **Códigos de respuesta:**
    - `200 OK` — escaneo completado (puede retornar lista vacía).
    """
    settings = get_settings()
    registry = get_camera_registry()

    active_slots = await registry.list_active()
    active_ids = {slot.camera_id for slot in active_slots}

    data = [_slot_to_dict(slot) for slot in active_slots]

    # Sondeo de índices USB conocidos que no tienen sesión activa.
    # Reutiliza settings.max_cameras como límite de índices a probar
    # (mismo valor que antes limitaba detect_available_cameras).
    for i in range(settings.max_cameras):
        candidate_id = str(i)
        if candidate_id in active_ids:
            continue
        state = await registry.probe(candidate_id)
        data.append(
            {
                "id": candidate_id,
                "type": "usb",
                "state": state.value,
                "connected_since": None,
                "retry_count": 0,
                "last_error": None,
            }
        )

    connected = any(item["state"] != CameraState.OFFLINE.value for item in data)
    in_use_count = sum(1 for item in data if item["state"] == CameraState.IN_USE.value)
    description = (
        f"{len(data)} cámara(s) conocida(s), {in_use_count} en uso."
        if data
        else "No se detectaron cámaras en el dispositivo."
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "connected": connected,
            "data": data,
            "error": None,
            "meta": {
                "total": len(data),
                "description": description,
            },
        },
    )
