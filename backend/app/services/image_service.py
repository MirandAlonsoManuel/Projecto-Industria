from __future__ import annotations

import cv2
import numpy as np


class ImageInputError(ValueError):
    pass


def decode_image(data: bytes) -> np.ndarray:
    if not data:
        raise ImageInputError("La imagen está vacía.")
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ImageInputError("No se pudo decodificar la imagen.")
    return image


def _crop_roi(image: np.ndarray, x: int, y: int, w: int, h: int) -> tuple[np.ndarray, list[int], tuple[int, int]]:
    height, width = image.shape[:2]
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ImageInputError("ROI contiene valores inválidos.")
    if x + w > width or y + h > height:
        raise ImageInputError("ROI está fuera de los límites de la imagen.")
    return image[y : y + h, x : x + w], [x, y, w, h], (x, y)


def resolve_roi(roi: str | None, image: np.ndarray) -> tuple[np.ndarray, list[int] | None, tuple[int, int]]:
    if roi is None or not roi.strip():
        return image, None, (0, 0)
    try:
        values = [int(value.strip()) for value in roi.split(",")]
    except Exception as exc:
        raise ImageInputError("ROI debe usar el formato x,y,width,height.") from exc
    if len(values) != 4:
        raise ImageInputError("ROI debe usar el formato x,y,width,height.")
    x, y, w, h = values
    return _crop_roi(image, x, y, w, h)


def resolve_roi_points(
    image: np.ndarray,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> tuple[np.ndarray, list[int], tuple[int, int]]:
    left = min(x1, x2)
    top = min(y1, y2)
    right = max(x1, x2)
    bottom = max(y1, y2)
    return _crop_roi(image, left, top, right - left, bottom - top)


def resolve_roi_request(
    image: np.ndarray,
    roi: str | None = None,
    x1: int | None = None,
    y1: int | None = None,
    x2: int | None = None,
    y2: int | None = None,
) -> tuple[np.ndarray, list[int] | None, tuple[int, int]]:
    points = [x1, y1, x2, y2]
    has_points = any(value is not None for value in points)
    if roi is not None and roi.strip() and has_points:
        raise ImageInputError("Use roi o x1,y1,x2,y2, no ambos formatos al mismo tiempo.")
    if has_points:
        if any(value is None for value in points):
            raise ImageInputError("Para ROI por dos puntos se requieren x1,y1,x2,y2.")
        return resolve_roi_points(image, int(x1), int(y1), int(x2), int(y2))
    return resolve_roi(roi, image)


def roi_points(roi: list[int] | None) -> list[int] | None:
    if roi is None:
        return None
    x, y, w, h = roi
    return [x, y, x + w, y + h]


def map_bbox(box: list[float], offset: tuple[int, int]) -> dict[str, float]:
    ox, oy = offset
    return {
        "x1": float(box[0] + ox),
        "y1": float(box[1] + oy),
        "x2": float(box[2] + ox),
        "y2": float(box[3] + oy),
    }


def map_polygon(points: list[list[float]], offset: tuple[int, int]) -> list[list[float]]:
    ox, oy = offset
    return [[float(x + ox), float(y + oy)] for x, y in points]
