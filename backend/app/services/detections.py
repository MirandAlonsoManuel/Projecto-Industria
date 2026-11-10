"""
Normalización de detecciones a coordenadas del frame ORIGINAL.

`InferenceService.localize` ya traslada las cajas con el desplazamiento de la
ROI (`map_bbox`). Aquí se valida el resultado antes de enviarlo:

- las coordenadas se recortan a [0, ancho] x [0, alto] del frame completo;
- una caja que tras recortar queda sin área (totalmente fuera, o degenerada)
  se descarta;
- una caja con valores no finitos o sin `bbox` se descarta.

El resultado no depende del tamaño en que un cliente muestre el video: no hay
escalado de canvas ni lógica de interfaz.
"""

from __future__ import annotations

import math
from typing import Any

_BBOX_KEYS = ("x1", "y1", "x2", "y2")


def _clamp(value: float, upper: int) -> float:
    return min(max(value, 0.0), float(upper))


def normalize_detections(
    detections: list[dict[str, Any]], frame_width: int, frame_height: int
) -> list[dict[str, Any]]:
    """Devuelve detecciones nuevas (no muta las recibidas) dentro del frame."""
    result: list[dict[str, Any]] = []
    for detection in detections:
        bbox = detection.get("bbox") if isinstance(detection, dict) else None
        if not isinstance(bbox, dict):
            continue
        try:
            x1, y1, x2, y2 = (float(bbox[key]) for key in _BBOX_KEYS)
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
            continue

        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        left, right = _clamp(left, frame_width), _clamp(right, frame_width)
        top, bottom = _clamp(top, frame_height), _clamp(bottom, frame_height)
        if right <= left or bottom <= top:
            continue

        fixed = dict(detection)
        fixed["bbox"] = {"x1": left, "y1": top, "x2": right, "y2": bottom}
        result.append(fixed)
    return result
