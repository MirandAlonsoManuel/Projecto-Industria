"""Detecciones en coordenadas absolutas del frame original (sin FastAPI)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.services.detections import normalize_detections
from app.services.image_service import map_bbox, resolve_roi_request

W, H = 200, 100


def _det(x1, y1, x2, y2, class_id=1, confidence=0.9):
    return {
        "class_id": class_id,
        "class_name": f"c{class_id}",
        "confidence": confidence,
        "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
    }


def test_full_frame_box_inside_limits_is_unchanged():
    detection = _det(10, 20, 60, 70)
    assert normalize_detections([detection], W, H) == [detection]


def test_each_detection_keeps_class_confidence_and_corners():
    (result,) = normalize_detections([_det(10, 20, 60, 70, class_id=3, confidence=0.5)], W, H)
    assert result["class_id"] == 3
    assert result["class_name"] == "c3"
    assert result["confidence"] == 0.5
    assert set(result["bbox"]) == {"x1", "y1", "x2", "y2"}


def test_roi_box_is_translated_to_the_original_frame():
    # Caja dentro del recorte (10,5)-(30,25) de una ROI que empieza en (100, 40)
    box = map_bbox([10, 5, 30, 25], (100, 40))
    (result,) = normalize_detections([{**_det(0, 0, 1, 1), "bbox": box}], W, H)
    assert result["bbox"] == {"x1": 110.0, "y1": 45.0, "x2": 130.0, "y2": 65.0}


def test_end_to_end_with_real_roi_crop_and_offset():
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    cropped, _, offset = resolve_roi_request(frame, None, 100, 40, 160, 90)
    assert cropped.shape[:2] == (50, 60) and offset == (100, 40)
    box = map_bbox([0, 0, 60, 50], offset)  # el recorte completo
    (result,) = normalize_detections([{**_det(0, 0, 1, 1), "bbox": box}], W, H)
    assert result["bbox"] == {"x1": 100.0, "y1": 40.0, "x2": 160.0, "y2": 90.0}


def test_box_exactly_on_frame_edges_is_kept():
    (result,) = normalize_detections([_det(0, 0, W, H)], W, H)
    assert result["bbox"] == {"x1": 0.0, "y1": 0.0, "x2": float(W), "y2": float(H)}


@pytest.mark.parametrize(
    "box, expected",
    [
        ((-10, 10, 50, 60), (0.0, 10.0, 50.0, 60.0)),  # se sale por la izquierda
        ((150, 10, 260, 60), (150.0, 10.0, 200.0, 60.0)),  # por la derecha
        ((10, -5, 50, 40), (10.0, 0.0, 50.0, 40.0)),  # por arriba
        ((10, 60, 50, 140), (10.0, 60.0, 50.0, 100.0)),  # por abajo
        ((-20, -20, 300, 300), (0.0, 0.0, 200.0, 100.0)),  # cubre todo el frame
    ],
)
def test_partially_outside_boxes_are_clamped(box, expected):
    (result,) = normalize_detections([_det(*box)], W, H)
    b = result["bbox"]
    assert (b["x1"], b["y1"], b["x2"], b["y2"]) == expected


@pytest.mark.parametrize(
    "box",
    [
        (210, 10, 260, 60),  # totalmente a la derecha
        (-50, 10, -5, 60),  # totalmente a la izquierda
        (10, 120, 50, 150),  # totalmente abajo
        (10, 10, 10, 50),  # ancho cero
        (10, 10, 50, 10),  # alto cero
        (200, 10, 250, 60),  # toca el borde sin área dentro
    ],
)
def test_boxes_without_area_inside_the_frame_are_dropped(box):
    assert normalize_detections([_det(*box)], W, H) == []


def test_inverted_corners_are_fixed():
    (result,) = normalize_detections([_det(60, 70, 10, 20)], W, H)
    assert result["bbox"] == {"x1": 10.0, "y1": 20.0, "x2": 60.0, "y2": 70.0}


@pytest.mark.parametrize(
    "bad",
    [
        {"class_id": 1},  # sin bbox
        {"bbox": None},
        {"bbox": {"x1": 1, "y1": 2, "x2": 3}},  # falta y2
        {"bbox": {"x1": "a", "y1": 2, "x2": 3, "y2": 4}},
        {"bbox": {"x1": math.nan, "y1": 2, "x2": 30, "y2": 40}},
        {"bbox": {"x1": 1, "y1": 2, "x2": math.inf, "y2": 40}},
    ],
)
def test_malformed_detections_are_dropped_without_breaking_the_rest(bad):
    good = _det(10, 20, 60, 70)
    assert normalize_detections([bad, good], W, H) == [good]


def test_input_is_not_mutated():
    original = _det(-10, 10, 50, 60)
    snapshot = {**original, "bbox": dict(original["bbox"])}
    normalize_detections([original], W, H)
    assert original == snapshot


def test_result_does_not_depend_on_any_display_size():
    # Mismas cajas, mismo frame: la salida es idéntica (no hay escala de canvas).
    boxes = [_det(10, 20, 60, 70), _det(-5, 0, 30, 30)]
    assert normalize_detections(boxes, W, H) == normalize_detections(list(boxes), W, H)
