from typing import Any

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class Detection(BaseModel):
    class_id: int
    class_name: str
    confidence: float
    bbox: BoundingBox


class LocalizationResponse(BaseModel):
    task: str = "localization"
    model_id: str
    image_width: int
    image_height: int
    roi: list[int] | None = None
    roi_points: list[int] | None = None
    detections: list[Detection]


class ClassificationItem(BaseModel):
    class_id: int
    class_name: str
    confidence: float


class ClassificationResponse(BaseModel):
    task: str = "classification"
    model_id: str
    roi: list[int] | None = None
    roi_points: list[int] | None = None
    predictions: list[ClassificationItem]


class OCRItem(BaseModel):
    text: str
    confidence: float
    polygon: list[list[float]]


class OCRResponse(BaseModel):
    task: str = "ocr"
    model_id: str
    roi: list[int] | None = None
    roi_points: list[int] | None = None
    results: list[OCRItem]


class AnomalyRegion(BaseModel):
    score: float
    area: int
    bbox: BoundingBox


class AnomalyResponse(BaseModel):
    task: str = "anomaly"
    model_id: str
    roi: list[int] | None = None
    roi_points: list[int] | None = None
    anomaly_score: float
    regions: list[AnomalyRegion]


class ModelInfo(BaseModel):
    id: str
    task: str
    backend: str
    default: bool = False
    enabled: bool = True
    available: bool
    loaded: bool
    config: dict[str, Any] = Field(default_factory=dict)
