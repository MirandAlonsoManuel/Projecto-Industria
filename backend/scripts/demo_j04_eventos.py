"""
Demostración reproducible de persistencia y consulta de eventos (J04).

Sobre una base SQLite en memoria, guarda eventos con detecciones y ejecuta los
filtros por cámara, clase, confianza y periodo. No necesita cámara ni red.

Ejecutar desde la carpeta backend:
    python scripts/demo_j04_eventos.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base, create_db_engine  # noqa: E402
from app.db.models import Camera, ProcessingRun, RunKind, SourceType  # noqa: E402
from app.services.detection_schemas import (  # noqa: E402
    DetectionEventInput, DetectionInput, DetectionValidationError, EventQuery,
)
from app.services.detection_store import (  # noqa: E402
    DetectionStoreService, DetectionStoreError,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def titulo(texto: str) -> None:
    print(f"\n{'─' * 70}\n{texto}\n{'─' * 70}")


def det(label, conf, clase, box=(0, 0, 10, 10)) -> DetectionInput:
    return DetectionInput(label=label, confidence=conf, class_id=clase,
                          x1=box[0], y1=box[1], x2=box[2], y2=box[3])


def resultado(etiqueta, page) -> None:
    print(f"  {etiqueta:<42} {page.total} evento(s)")


def main() -> None:
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        cam_a = Camera(name="Línea A", source="0", source_type=SourceType.USB)
        cam_b = Camera(name="Línea B", source="1", source_type=SourceType.USB)
        run_a = ProcessingRun(camera=cam_a, kind=RunKind.INFERENCE_STREAM, model_id="yolo", created_at=T0)
        run_b = ProcessingRun(camera=cam_b, kind=RunKind.INFERENCE_STREAM, model_id="yolo", created_at=T0)
        run_a.start(at=T0)
        run_b.start(at=T0)
        db.add_all([cam_a, cam_b])
        db.flush()
        svc = DetectionStoreService(db)

        titulo("1. Guardar eventos")
        svc.save_event(DetectionEventInput(
            run_id=run_a.id, frame_seq=1, captured_at=T0,
            detections=[det("pieza", 0.95, 1), det("tornillo", 0.60, 2)]))
        svc.save_event(DetectionEventInput(
            run_id=run_a.id, frame_seq=2, captured_at=T0 + timedelta(hours=1),
            detections=[det("tornillo", 0.80, 2)]))
        svc.save_event(DetectionEventInput(
            run_id=run_a.id, frame_seq=3, captured_at=T0 + timedelta(hours=2),
            detections=[det("pieza", 0.50, 1)]))
        svc.save_event(DetectionEventInput(
            run_id=run_b.id, frame_seq=1, captured_at=T0 + timedelta(minutes=30),
            detections=[det("pieza", 0.99, 1)]))
        print("  4 eventos guardados (3 en Línea A, 1 en Línea B).")

        titulo("2. Filtros")
        resultado("Sin filtros (todos):", svc.query(EventQuery()))
        resultado("Cámara = Línea A:", svc.query(EventQuery(camera_id=cam_a.id)))
        resultado("Clase = tornillo (class_id 2):", svc.query(EventQuery(class_id=2)))
        resultado("Etiqueta = pieza:", svc.query(EventQuery(label="pieza")))
        resultado("Confianza >= 0.90:", svc.query(EventQuery(min_confidence=0.9)))
        resultado("Periodo [T0, T0+90min):",
                  svc.query(EventQuery(start=T0, end=T0 + timedelta(minutes=90))))
        resultado("Línea A + tornillo + conf >= 0.70:",
                  svc.query(EventQuery(camera_id=cam_a.id, class_id=2, min_confidence=0.7)))

        titulo("3. Un evento filtrado conserva todas sus detecciones")
        page = svc.query(EventQuery(camera_id=cam_a.id, min_confidence=0.9))
        ev = page.events[0]
        print(f"  Filtro confianza >= 0.90 encontró el frame {ev.frame_seq}, "
              f"con {len(ev.detections)} detecciones:")
        for d in ev.detections:
            print(f"    - {d.label} (confianza {d.confidence})")
        print("  La detección de 0.60 sigue ahí: el filtro elige frames, no recorta su contenido.")

        titulo("4. Paginación")
        p1 = svc.query(EventQuery(limit=2, offset=0))
        p2 = svc.query(EventQuery(limit=2, offset=2))
        print(f"  Página 1: {len(p1.events)} eventos, ¿hay más? {p1.has_more}")
        print(f"  Página 2: {len(p2.events)} eventos, ¿hay más? {p2.has_more}")

        titulo("5. Operaciones inválidas")
        try:
            svc.save_event(DetectionEventInput(
                run_id=run_a.id, frame_seq=9, captured_at=T0,
                detections=[det("mala", 1.5, 1)]))  # confianza > 1
        except DetectionValidationError as exc:
            print(f"  ✓ Detección con confianza inválida [{exc.field}]: {exc}")
        try:
            svc.save_event(DetectionEventInput(
                run_id=run_a.id, frame_seq=1, captured_at=T0, detections=[det("pieza", 0.9, 1)]))
        except DetectionStoreError as exc:
            print(f"  ✓ Evento duplicado para un frame [{exc.code}]: {exc}")

    engine.dispose()


if __name__ == "__main__":
    main()
