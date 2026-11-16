"""
Persistencia y consulta de eventos de detección (J04).

Dos responsabilidades:

  - guardar un evento con sus detecciones, validado contra el modelo aprobado
    y verificando que la corrida exista y que la cámara del evento sea la suya;
  - consultar eventos con filtros combinables por cámara, clase, confianza y
    periodo, con paginación y conteo total.

El servicio no hace commit: trabaja sobre la sesión que recibe, igual que los
repositorios y el servicio de fuentes de J03.

Nota sobre el filtro de detecciones: cuando se filtra por clase, etiqueta o
confianza, un evento aparece si tiene *al menos una* detección que cumple. Las
detecciones que trae cada evento en la respuesta son todas las del evento, no
solo las que pasaron el filtro, para no dar una imagen falsa del frame. Esto se
documenta en el método `query`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Camera,
    Detection,
    DetectionEvent,
    ProcessingRun,
)
from app.services.detection_schemas import (
    DetectionEventInput,
    DetectionEventRead,
    DetectionValidationError,
    EventPage,
    EventQuery,
)


class DetectionStoreError(Exception):
    code = "DETECTION_STORE_ERROR"


class RunNotFoundError(DetectionStoreError):
    code = "RUN_NOT_FOUND"


class DuplicateEventError(DetectionStoreError):
    """Ya existe un evento para ese frame en esa corrida."""

    code = "EVENT_DUPLICATE"


class DetectionStoreService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Guardar ──────────────────────────────────────────────────────────────

    def save_event(self, data: DetectionEventInput) -> DetectionEventRead:
        """
        Guarda un evento con sus detecciones.

        Valida el evento contra el modelo aprobado, resuelve la cámara desde la
        corrida (para no confiar en un camera_id enviado por fuera) y rechaza un
        segundo evento para el mismo frame de la misma corrida.

        Raises:
            DetectionValidationError: el evento o una detección es inválido.
            RunNotFoundError: la corrida no existe.
            DuplicateEventError: ya hay un evento para ese frame.
        """
        clean = data.validated()

        run = self.session.get(ProcessingRun, clean.run_id)
        if run is None:
            raise RunNotFoundError(f"No existe la corrida '{clean.run_id}'.")

        ya_existe = self.session.scalar(
            select(exists().where(
                DetectionEvent.run_id == clean.run_id,
                DetectionEvent.frame_seq == clean.frame_seq,
            ))
        )
        if ya_existe:
            raise DuplicateEventError(
                f"Ya hay un evento para el frame {clean.frame_seq} de la corrida."
            )

        event = DetectionEvent(
            run_id=clean.run_id,
            camera_id=run.camera_id,  # la cámara se toma de la corrida, no del input
            frame_seq=clean.frame_seq,
            captured_at=clean.captured_at,
            processed_at=clean.processed_at,
            frame_width=clean.frame_width,
            frame_height=clean.frame_height,
            roi=clean.roi,
            detections=[d.to_model() for d in clean.detections],
        )
        self.session.add(event)
        self.session.flush()
        return DetectionEventRead.from_model(event)

    # ── Consultar ────────────────────────────────────────────────────────────

    def query(self, q: EventQuery) -> EventPage:
        """
        Consulta eventos con filtros combinables (todos opcionales, unidos con Y):

          - camera_id, run_id: igualdad exacta;
          - start / end: por fecha de captura (inicio inclusivo, fin exclusivo);
          - label, class_id, min_confidence: el evento aparece si tiene al menos
            una detección que cumple.

        Cada evento devuelto trae TODAS sus detecciones, no solo las que pasaron
        el filtro, para no dar una imagen incompleta del frame. Los resultados se
        ordenan por fecha de captura descendente y se paginan con limit/offset.
        """
        clean = q.validated()
        base = self._apply_filters(select(DetectionEvent), clean)

        total = self.session.scalar(
            self._apply_filters(select(func.count(DetectionEvent.id.distinct())), clean)
        ) or 0

        stmt = (
            base.order_by(DetectionEvent.captured_at.desc(), DetectionEvent.id)
            .offset(clean.offset)
            .limit(clean.limit)
            .options(selectinload(DetectionEvent.detections))
        )
        eventos = list(self.session.scalars(stmt).unique())
        return EventPage(
            events=[DetectionEventRead.from_model(e) for e in eventos],
            total=total, limit=clean.limit, offset=clean.offset,
        )

    def get_event(self, event_id: str) -> Optional[DetectionEventRead]:
        ev = self.session.get(DetectionEvent, event_id)
        return DetectionEventRead.from_model(ev) if ev is not None else None

    def _apply_filters(self, stmt, q: EventQuery):
        if q.camera_id is not None:
            stmt = stmt.where(DetectionEvent.camera_id == q.camera_id)
        if q.run_id is not None:
            stmt = stmt.where(DetectionEvent.run_id == q.run_id)
        if q.start is not None:
            stmt = stmt.where(DetectionEvent.captured_at >= q.start)
        if q.end is not None:
            stmt = stmt.where(DetectionEvent.captured_at < q.end)

        if q.filters_detections:
            # El evento califica si EXISTE una detección suya que cumpla los
            # filtros de detección. Un EXISTS correlacionado evita duplicar
            # filas del evento cuando varias detecciones cumplen.
            cond = [Detection.event_id == DetectionEvent.id]
            if q.label is not None:
                cond.append(Detection.label == q.label)
            if q.class_id is not None:
                cond.append(Detection.class_id == q.class_id)
            if q.min_confidence is not None:
                cond.append(Detection.confidence >= q.min_confidence)
            stmt = stmt.where(exists().where(*cond))
        return stmt
