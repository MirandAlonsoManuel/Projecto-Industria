import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.services.image_service import ImageInputError, resolve_roi, resolve_roi_points, resolve_roi_request


client = TestClient(app)


def _png(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


def test_models_endpoint() -> None:
    response = client.get("/models")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert "yolo26n-localization" in ids
    assert "efficientnet-b0-classification" in ids
    assert "paddleocr-es" in ids
    assert "reference-diff-v1" in ids


def test_roi_validation() -> None:
    image = np.zeros((100, 120, 3), dtype=np.uint8)
    cropped, roi, offset = resolve_roi("10,20,30,40", image)
    assert cropped.shape[:2] == (40, 30)
    assert roi == [10, 20, 30, 40]
    assert offset == (10, 20)


def test_roi_two_points() -> None:
    image = np.zeros((100, 120, 3), dtype=np.uint8)
    cropped, roi, offset = resolve_roi_points(image, 10, 20, 40, 60)
    assert cropped.shape[:2] == (40, 30)
    assert roi == [10, 20, 30, 40]
    assert offset == (10, 20)


def test_roi_reverse_drag() -> None:
    image = np.zeros((100, 120, 3), dtype=np.uint8)
    cropped, roi, offset = resolve_roi_points(image, 40, 60, 10, 20)
    assert cropped.shape[:2] == (40, 30)
    assert roi == [10, 20, 30, 40]
    assert offset == (10, 20)


def test_partial_roi_points() -> None:
    image = np.zeros((100, 120, 3), dtype=np.uint8)
    try:
        resolve_roi_request(image, x1=10, y1=20, x2=40)
    except ImageInputError:
        return
    raise AssertionError("Se esperaba ImageInputError")


def test_invalid_roi() -> None:
    image = np.zeros((100, 120, 3), dtype=np.uint8)
    try:
        resolve_roi("100,90,50,50", image)
    except ImageInputError:
        return
    raise AssertionError("Se esperaba ImageInputError")


def test_anomaly_endpoint() -> None:
    reference = np.zeros((160, 200, 3), dtype=np.uint8)
    target = reference.copy()
    cv2.rectangle(target, (60, 50), (120, 110), (255, 255, 255), -1)
    response = client.post(
        "/inference/anomaly?difference_threshold=20",
        files={
            "image": ("target.png", _png(target), "image/png"),
            "reference_image": ("reference.png", _png(reference), "image/png"),
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["model_id"] == "reference-diff-v1"
    assert len(payload["regions"]) >= 1


def test_anomaly_roi_coordinates() -> None:
    reference = np.zeros((200, 240, 3), dtype=np.uint8)
    target = reference.copy()
    cv2.rectangle(target, (100, 80), (140, 120), (255, 255, 255), -1)
    response = client.post(
        "/inference/anomaly?difference_threshold=20&x1=80&y1=60&x2=180&y2=160",
        files={
            "image": ("target.png", _png(target), "image/png"),
            "reference_image": ("reference.png", _png(reference), "image/png"),
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["roi"] == [80, 60, 100, 100]
    assert payload["roi_points"] == [80, 60, 180, 160]
    box = payload["regions"][0]["bbox"]
    assert box["x1"] >= 80
    assert box["y1"] >= 60
