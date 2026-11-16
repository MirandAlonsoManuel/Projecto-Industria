"""
Mensajes de control del WebSocket /ws/inference-stream (update_roi).

Sin dependencias de FastAPI: este módulo solo valida, guarda la configuración
activa y construye las respuestas estructuradas. `stream_runner` lo conecta al
socket.

Contrato (JSON de texto, cliente -> servidor):

    {"type": "update_roi", "request_id": "abc", "roi": {"x1": 10, "y1": 20, "x2": 300, "y2": 240}}
    {"type": "update_roi", "request_id": "abc", "roi": null}      # frame completo

`roi` usa coordenadas absolutas del frame original (esquinas en cualquier
orden). `request_id` es opcional y se devuelve tal cual.

Respuestas (servidor -> cliente, JSON de texto):

    {"type": "roi_updated", "ok": true, "request_id": ..., "roi": {...}|null,
     "roi_version": 3, "frame_width": 640, "frame_height": 480}

    {"type": "error", "error": "INVALID_ROI" | "ROI_OUT_OF_FRAME" |
     "INVALID_MESSAGE" | "UNKNOWN_MESSAGE_TYPE", "recoverable": true,
     "request_id": ..., "description": "...", "roi": <ROI activa>, "roi_version": 2}

Todo error es recuperable: el socket sigue abierto y se conserva la última ROI
válida (la que aparece en el propio error).

Atomicidad: la configuración activa es un objeto inmutable (`RoiConfig`) que se
reemplaza con una sola asignación. El stream toma una instantánea por frame, de
modo que cada frame se infiere con una ROI completa y consistente, y el mensaje
informa qué ROI/versión se usó.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from app.services.image_service import ImageInputError, resolve_roi_request

# (x1, y1, x2, y2) absolutos en el frame original, con x1 < x2 y y1 < y2
Roi = tuple[int, int, int, int]

INVALID_ROI = "INVALID_ROI"
ROI_OUT_OF_FRAME = "ROI_OUT_OF_FRAME"
INVALID_MESSAGE = "INVALID_MESSAGE"
UNKNOWN_MESSAGE_TYPE = "UNKNOWN_MESSAGE_TYPE"

MAX_CONTROL_MESSAGE_CHARS = 4096
_MAX_REQUEST_ID_CHARS = 64
_ROI_KEYS = frozenset({"x1", "y1", "x2", "y2"})

# Lado de un frame "virtual" para validar formato y valores cuando aún no se
# conoce el tamaño real. Es una vista broadcast: no ocupa memoria.
_VIRTUAL_SIDE = 1 << 20


class RoiOutOfFrame(Exception):
    """La ROI activa no cabe en el frame actual (lo lanza la función de inferencia)."""


class ControlError(Exception):
    def __init__(self, code: str, description: str) -> None:
        super().__init__(description)
        self.code = code
        self.description = description


@dataclass(frozen=True)
class RoiConfig:
    version: int = 0
    roi: Optional[Roi] = None


def roi_to_dict(roi: Optional[Roi]) -> Optional[dict]:
    if roi is None:
        return None
    return {"x1": roi[0], "y1": roi[1], "x2": roi[2], "y2": roi[3]}


def _virtual_frame(width: int = _VIRTUAL_SIDE, height: int = _VIRTUAL_SIDE) -> np.ndarray:
    return np.broadcast_to(np.zeros((1, 1, 3), dtype=np.uint8), (height, width, 3))


def _to_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControlError(INVALID_ROI, f"{name} debe ser un número entero.")
    if isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            raise ControlError(INVALID_ROI, f"{name} debe ser un número entero.")
        return int(value)
    return value


def _roi_from_resolved(resolved: Optional[list]) -> Optional[Roi]:
    if resolved is None:
        return None
    x, y, w, h = resolved
    return (x, y, x + w, y + h)


def parse_roi(raw: Any) -> Optional[Roi]:
    """Valida el campo `roi` de update_roi (formato y valores, sin mirar el frame)."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != _ROI_KEYS:
        raise ControlError(INVALID_ROI, "roi debe ser null o un objeto con x1, y1, x2, y2.")
    x1, y1, x2, y2 = (_to_int(raw[key], key) for key in ("x1", "y1", "x2", "y2"))
    try:
        _, resolved, _ = resolve_roi_request(_virtual_frame(), None, x1, y1, x2, y2)
    except ImageInputError as exc:
        raise ControlError(INVALID_ROI, str(exc)) from exc
    return _roi_from_resolved(resolved)


class StreamControl:
    """Estado de control de UNA conexión: se crea al conectar y muere al desconectar."""

    def __init__(self) -> None:
        self._config = RoiConfig()
        self._frame_size: Optional[tuple[int, int]] = None
        # Aviso para enviar justo después del mensaje "connected" (ROI inicial inválida)
        self.startup_notice: Optional[dict] = None

    # -- estado -------------------------------------------------------------

    @property
    def config(self) -> RoiConfig:
        """Instantánea inmutable: leerla es atómico."""
        return self._config

    @property
    def frame_size(self) -> Optional[tuple[int, int]]:
        return self._frame_size

    def set_frame_size(self, width: int, height: int) -> None:
        self._frame_size = (width, height)

    # -- ROI inicial (query params al conectar) --------------------------------

    def set_initial_roi(
        self,
        roi: Optional[str] = None,
        x1: Optional[int] = None,
        y1: Optional[int] = None,
        x2: Optional[int] = None,
        y2: Optional[int] = None,
    ) -> None:
        """
        Aplica la ROI de la URL (mismos formatos que los endpoints HTTP). Si es
        inválida no se cierra el socket: se avisa con un error recuperable y el
        stream arranca con el frame completo.
        """
        try:
            _, resolved, _ = resolve_roi_request(_virtual_frame(), roi, x1, y1, x2, y2)
        except ImageInputError as exc:
            self.startup_notice = self._error(INVALID_ROI, str(exc), None)
            return
        self._config = RoiConfig(0, _roi_from_resolved(resolved))

    # -- update_roi --------------------------------------------------------------

    def apply_update(self, raw_roi: Any) -> RoiConfig:
        roi = parse_roi(raw_roi)
        if roi is not None and self._frame_size is not None:
            width, height = self._frame_size
            if roi[2] > width or roi[3] > height:
                raise ControlError(
                    ROI_OUT_OF_FRAME,
                    f"La ROI está fuera del frame ({width}x{height}).",
                )
        new = RoiConfig(self._config.version + 1, roi)
        self._config = new  # una sola asignación: atómico
        return new

    def handle_text(self, text: str) -> dict:
        """Procesa un mensaje de control y devuelve SIEMPRE una respuesta."""
        if len(text) > MAX_CONTROL_MESSAGE_CHARS:
            return self._error(INVALID_MESSAGE, "El mensaje de control es demasiado grande.", None)
        try:
            data = json.loads(text)
        except ValueError:
            return self._error(INVALID_MESSAGE, "El mensaje debe ser JSON válido.", None)
        if not isinstance(data, dict):
            return self._error(INVALID_MESSAGE, "El mensaje debe ser un objeto JSON.", None)

        request_id = data.get("request_id")
        if isinstance(request_id, str):
            request_id = request_id[:_MAX_REQUEST_ID_CHARS]
        elif not isinstance(request_id, int) or isinstance(request_id, bool):
            request_id = None

        message_type = data.get("type")
        if message_type != "update_roi":
            return self._error(
                UNKNOWN_MESSAGE_TYPE, "Tipo de mensaje no soportado: use 'update_roi'.", request_id
            )
        if "roi" not in data:
            return self._error(
                INVALID_MESSAGE, "Falta el campo roi (use null para el frame completo).", request_id
            )
        try:
            config = self.apply_update(data["roi"])
        except ControlError as exc:
            return self._error(exc.code, exc.description, request_id)

        width, height = self._frame_size if self._frame_size else (None, None)
        return {
            "type": "roi_updated",
            "ok": True,
            "request_id": request_id,
            "roi": roi_to_dict(config.roi),
            "roi_version": config.version,
            "frame_width": width,
            "frame_height": height,
        }

    def _error(self, code: str, description: str, request_id: Any) -> dict:
        config = self._config
        return {
            "type": "error",
            "error": code,
            "recoverable": True,
            "request_id": request_id,
            "description": description,
            "roi": roi_to_dict(config.roi),
            "roi_version": config.version,
        }
