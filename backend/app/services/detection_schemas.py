"""
Esquemas de entrada, filtro y salida para eventos de detección (J04).

Tres grupos:

  - entrada: `DetectionInput` y `DetectionEventInput`, lo que llega para guardar
    un evento con sus detecciones, validado antes de tocar la base;
  - consulta: `EventQuery`, los filtros por cámara, clase, confianza y periodo,
    con su validación;
  - salida: `DetectionRead`, `DetectionEventRead` y `EventPage`, la vista que se
    entrega, con paginación.

El modelo aprobado de detección (J01, contrato E05/E06) exige que cada caja
tenga área (`x2 > x1`, `y2 > y1`), que la confianza esté entre 0 y 1, y que la
etiqueta no esté vacía. Aquí se valida antes de guardar, para dar un error
claro en vez de un fallo de la base.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.db.models import Detection, DetectionEvent


class DetectionValidationError(ValueError):
    """Un evento o una detección no cumple el modelo aprobado."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


def _require_aware(field: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise DetectionValidationError(field, "Se esperaba una fecha y hora.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise DetectionValidationError(
            field, "La fecha debe incluir zona horaria (por ejemplo, UTC)."
        )
    return value.astimezone(timezone.utc)


# ── Entrada ───────────────────────────────────────────────────────────────────

@dataclass
class DetectionInput:
    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    class_id: Optional[int] = None
    attributes: Optional[dict] = None

    def validated(self) -> "DetectionInput":
        label = self.label.strip() if isinstance(self.label, str) else ""
        if not label:
            raise DetectionValidationError("label", "La etiqueta no puede estar vacía.")
        if not (0.0 <= self.confidence <= 1.0):
            raise DetectionValidationError("confidence", "La confianza debe estar entre 0 y 1.")
        if self.class_id is not None and self.class_id < 0:
            raise DetectionValidationError("class_id", "class_id no puede ser negativo.")
        if self.x1 < 0 or self.y1 < 0:
            raise DetectionValidationError("box", "La caja empieza fuera del frame.")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise DetectionValidationError("box", "La caja no tiene área (x2>x1, y2>y1).")
        return DetectionInput(
            label=label, confidence=float(self.confidence),
            x1=float(self.x1), y1=float(self.y1), x2=float(self.x2), y2=float(self.y2),
            class_id=self.class_id, attributes=self.attributes,
        )

    def to_model(self) -> Detection:
        return Detection(
            label=self.label, class_id=self.class_id, confidence=self.confidence,
            x1=self.x1, y1=self.y1, x2=self.x2, y2=self.y2, attributes=self.attributes,
        )


@dataclass
class DetectionEventInput:
    run_id: str
    frame_seq: int
    captured_at: datetime
    processed_at: Optional[datetime] = None
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    roi: Optional[list] = None
    detections: list[DetectionInput] = field(default_factory=list)

    def validated(self) -> "DetectionEventInput":
        if not self.run_id:
            raise DetectionValidationError("run_id", "Falta la corrida del evento.")
        if self.frame_seq < 0:
            raise DetectionValidationError("frame_seq", "frame_seq no puede ser negativo.")
        captured = _require_aware("captured_at", self.captured_at)
        processed = (
            _require_aware("processed_at", self.processed_at)
            if self.processed_at is not None else datetime.now(timezone.utc)
        )
        if processed < captured:
            raise DetectionValidationError(
                "processed_at", "El procesamiento no puede ser anterior a la captura."
            )
        if (self.frame_width is None) != (self.frame_height is None):
            raise DetectionValidationError(
                "frame_size", "El ancho y el alto del frame se informan juntos."
            )
        if self.frame_width is not None and (self.frame_width <= 0 or self.frame_height <= 0):
            raise DetectionValidationError("frame_size", "El tamaño del frame debe ser positivo.")
        detections = [d.validated() for d in self.detections]
        return DetectionEventInput(
            run_id=self.run_id, frame_seq=self.frame_seq,
            captured_at=captured, processed_at=processed,
            frame_width=self.frame_width, frame_height=self.frame_height,
            roi=self.roi, detections=detections,
        )


# ── Consulta ──────────────────────────────────────────────────────────────────

@dataclass
class EventQuery:
    """Filtros para consultar eventos. Todos son opcionales y se combinan con Y."""

    camera_id: Optional[str] = None
    run_id: Optional[str] = None
    label: Optional[str] = None
    class_id: Optional[int] = None
    min_confidence: Optional[float] = None
    start: Optional[datetime] = None          # inclusivo
    end: Optional[datetime] = None            # exclusivo
    limit: int = 100
    offset: int = 0

    def validated(self) -> "EventQuery":
        if self.min_confidence is not None and not (0.0 <= self.min_confidence <= 1.0):
            raise DetectionValidationError("min_confidence", "La confianza debe estar entre 0 y 1.")
        start = _require_aware("start", self.start) if self.start is not None else None
        end = _require_aware("end", self.end) if self.end is not None else None
        if start is not None and end is not None and end <= start:
            raise DetectionValidationError("period", "El fin del periodo debe ser posterior al inicio.")
        if not (1 <= self.limit <= 1000):
            raise DetectionValidationError("limit", "limit debe estar entre 1 y 1000.")
        if self.offset < 0:
            raise DetectionValidationError("offset", "offset no puede ser negativo.")
        return EventQuery(
            camera_id=self.camera_id, run_id=self.run_id, label=self.label,
            class_id=self.class_id, min_confidence=self.min_confidence,
            start=start, end=end, limit=self.limit, offset=self.offset,
        )

    @property
    def filters_detections(self) -> bool:
        """¿El filtro mira dentro de las detecciones (clase, etiqueta, confianza)?"""
        return any(v is not None for v in (self.label, self.class_id, self.min_confidence))


# ── Salida ────────────────────────────────────────────────────────────────────

@dataclass
class DetectionRead:
    id: str
    label: str
    class_id: Optional[int]
    confidence: float
    box: list[float]
    attributes: Optional[dict]

    @classmethod
    def from_model(cls, d: Detection) -> "DetectionRead":
        return cls(
            id=d.id, label=d.label, class_id=d.class_id,
            confidence=round(d.confidence, 4),
            box=[d.x1, d.y1, d.x2, d.y2], attributes=d.attributes,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "class_id": self.class_id,
            "confidence": self.confidence, "box": self.box, "attributes": self.attributes,
        }


@dataclass
class DetectionEventRead:
    id: str
    run_id: str
    camera_id: str
    frame_seq: int
    captured_at: datetime
    processed_at: datetime
    frame_size: Optional[list[int]]
    roi: Optional[list]
    detections: list[DetectionRead]

    @classmethod
    def from_model(cls, ev: DetectionEvent) -> "DetectionEventRead":
        size = [ev.frame_width, ev.frame_height] if ev.frame_width is not None else None
        return cls(
            id=ev.id, run_id=ev.run_id, camera_id=ev.camera_id, frame_seq=ev.frame_seq,
            captured_at=ev.captured_at, processed_at=ev.processed_at,
            frame_size=size, roi=ev.roi,
            detections=[DetectionRead.from_model(d) for d in ev.detections],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "run_id": self.run_id, "camera_id": self.camera_id,
            "frame_seq": self.frame_seq,
            "captured_at": self.captured_at.isoformat(),
            "processed_at": self.processed_at.isoformat(),
            "frame_size": self.frame_size, "roi": self.roi,
            "detections": [d.to_dict() for d in self.detections],
        }


@dataclass
class EventPage:
    """Una página de resultados, con lo necesario para pedir la siguiente."""

    events: list[DetectionEventRead]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.events) < self.total

    def to_dict(self) -> dict:
        return {
            "events": [e.to_dict() for e in self.events],
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
            "has_more": self.has_more,
        }
