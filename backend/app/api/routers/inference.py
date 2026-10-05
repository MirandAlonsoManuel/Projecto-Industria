from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, WebSocket

from app.api.ws_camera import run_camera_stream
from app.core.config import get_settings
from app.schemas.inference import (
    AnomalyResponse,
    ClassificationResponse,
    LocalizationResponse,
    ModelInfo,
    OCRResponse,
)
from app.services.camera_service import encode_ws_message
from app.services.camera_session_manager import camera_session_manager
from app.services.image_service import ImageInputError, decode_image, resolve_roi_request, roi_points
from app.services.inference_service import InferenceError, inference_service
from app.services.model_registry import ModelRegistryError

router = APIRouter(tags=["inference"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ImageInputError, ModelRegistryError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, InferenceError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _roi_query(
    frame,
    roi: str | None,
    x1: int | None,
    y1: int | None,
    x2: int | None,
    y2: int | None,
):
    return resolve_roi_request(frame, roi, x1, y1, x2, y2)


@router.get("/models", response_model=list[ModelInfo])
def list_models() -> list[dict]:
    return inference_service.list_models()


@router.post("/inference/localization", response_model=LocalizationResponse)
async def localization(
    image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    conf: float = Query(default=0.25, ge=0.0, le=1.0),
    iou: float = Query(default=0.45, ge=0.0, le=1.0),
    roi: str | None = Query(default=None),
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, offset = _roi_query(frame, roi, x1, y1, x2, y2)
        selected, detections = inference_service.localize(cropped, model_id, conf, iou, offset)
        height, width = frame.shape[:2]
        return {
            "model_id": selected,
            "image_width": width,
            "image_height": height,
            "roi": roi_value,
            "roi_points": roi_points(roi_value),
            "detections": detections,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/classification", response_model=ClassificationResponse)
async def classification(
    image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    top_k: int = Query(default=5, ge=1, le=20),
    roi: str | None = Query(default=None),
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, _ = _roi_query(frame, roi, x1, y1, x2, y2)
        selected, predictions = inference_service.classify(cropped, model_id, top_k)
        return {
            "model_id": selected,
            "roi": roi_value,
            "roi_points": roi_points(roi_value),
            "predictions": predictions,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/ocr", response_model=OCRResponse)
async def ocr(
    image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    roi: str | None = Query(default=None),
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        cropped, roi_value, offset = _roi_query(frame, roi, x1, y1, x2, y2)
        selected, results = inference_service.ocr(cropped, model_id, offset)
        return {
            "model_id": selected,
            "roi": roi_value,
            "roi_points": roi_points(roi_value),
            "results": results,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/inference/anomaly", response_model=AnomalyResponse)
async def anomaly(
    image: UploadFile = File(...),
    reference_image: UploadFile = File(...),
    model_id: str | None = Query(default=None),
    difference_threshold: int | None = Query(default=None, ge=0, le=255),
    roi: str | None = Query(default=None),
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> dict:
    try:
        frame = decode_image(await image.read())
        reference = decode_image(await reference_image.read())
        cropped, roi_value, offset = _roi_query(frame, roi, x1, y1, x2, y2)
        reference_cropped, _, _ = _roi_query(reference, roi, x1, y1, x2, y2)
        selected, score, regions = inference_service.anomaly_reference(
            cropped,
            reference_cropped,
            model_id,
            difference_threshold,
            offset,
        )
        return {
            "model_id": selected,
            "roi": roi_value,
            "roi_points": roi_points(roi_value),
            "anomaly_score": score,
            "regions": regions,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.websocket("/ws/inference-stream")
async def inference_stream(
    websocket: WebSocket,
    camera_id: str = Query(default="0"),
    model_id: str | None = Query(default=None),
    conf: float = Query(default=0.25, ge=0.0, le=1.0),
    iou: float = Query(default=0.45, ge=0.0, le=1.0),
    infer_every_n_frames: int = Query(default=3, ge=1, le=120),
    roi: str | None = Query(default=None),
    x1: int | None = Query(default=None),
    y1: int | None = Query(default=None),
    x2: int | None = Query(default=None),
    y2: int | None = Query(default=None),
) -> None:
    """
    Transmite frames con detecciones del modelo de localización.

    Comparte la sesión y el ciclo de vida con `/ws/stream`: solo puede haber un
    cliente entre ambos endpoints, y los mensajes, errores y códigos de cierre
    son los mismos. Si la inferencia falla, el cliente recibe PROCESSING_ERROR
    y la conexión se cierra con 1011.
    """
    settings = get_settings()
    loop = asyncio.get_running_loop()
    last_detections: list[dict] = []

    async def on_frame(frame, session, frame_index: int) -> bytes:
        nonlocal last_detections
        if frame_index % infer_every_n_frames == 0:
            cropped, _, offset = _roi_query(frame, roi, x1, y1, x2, y2)
            _, last_detections = await loop.run_in_executor(
                None,
                lambda: inference_service.localize(cropped, model_id, conf, iou, offset),
            )
        detections = last_detections
        return await loop.run_in_executor(
            None,
            lambda: encode_ws_message(
                frame, detections, session.metrics.fps_current, camera_id, settings.jpeg_quality
            ),
        )

    await run_camera_stream(
        websocket,
        camera_session_manager,
        camera_id,
        on_frame,
        welcome="Cámara detectada. Iniciando inferencia.",
    )
