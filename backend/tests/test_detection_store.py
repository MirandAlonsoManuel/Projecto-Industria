"""
Pruebas de persistencia y consulta de eventos de detección — J04.

Cada prueba usa una base SQLite en memoria, nueva por caso, y trabaja a través
de `DetectionStoreService`, como lo haría la API.

Criterios cubiertos:
  C1  Los eventos cumplen el modelo de detección aprobado.
  C2  Los filtros producen resultados correctos.
  C3  Las relaciones entre cámara, detección y metadatos conservan integridad.

Ejecutar:
    cd backend
    python -m pytest tests/test_detection_store.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base, create_db_engine
from app.db.models import Camera, Detection, DetectionEvent, ProcessingRun, RunKind, SourceType
from app.services.detection_schemas import (
    DetectionEventInput,
    DetectionInput,
    DetectionValidationError,
    EventQuery,
)
from app.services.detection_store import (
    DetectionStoreService,
    DuplicateEventError,
    RunNotFoundError,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def svc(db) -> DetectionStoreService:
    return DetectionStoreService(db)


@pytest.fixture
def run(db) -> ProcessingRun:
    cam = Camera(name="Línea 1", source="0", source_type=SourceType.USB)
    r = ProcessingRun(camera=cam, kind=RunKind.INFERENCE_STREAM, model_id="yolo26n", created_at=T0)
    r.start(at=T0)
    db.add(cam)
    db.flush()
    return r


def det(label="pieza", conf=0.9, clase=1, box=(0, 0, 10, 10), attrs=None) -> DetectionInput:
    return DetectionInput(
        label=label, confidence=conf, class_id=clase,
        x1=box[0], y1=box[1], x2=box[2], y2=box[3], attributes=attrs,
    )


def evento(run, seq=1, segundos=2, dets=None, **kwargs) -> DetectionEventInput:
    return DetectionEventInput(
        run_id=run.id, frame_seq=seq,
        captured_at=T0 + timedelta(seconds=segundos),
        detections=dets if dets is not None else [det()],
        **kwargs,
    )


# ── C1: los eventos cumplen el modelo aprobado ───────────────────────────────

def test_c1_guardar_evento_con_detecciones(svc, run):
    r = svc.save_event(evento(run, dets=[
        det("pieza", 0.91, 1, (40, 60, 200, 260)),
        det("tornillo", 0.72, 2, (120, 300, 180, 360)),
    ], frame_width=640, frame_height=480, roi=[[0, 0], [640, 480]]))

    assert r.frame_seq == 1
    assert len(r.detections) == 2
    assert r.frame_size == [640, 480]
    assert r.detections[0].box == [40, 60, 200, 260]


def test_c1_evento_sin_detecciones_es_valido(svc, run):
    """Un frame procesado sin hallazgos: evento sin detecciones (no es lo mismo que no procesarlo)."""
    r = svc.save_event(evento(run, dets=[]))
    assert r.detections == []


@pytest.mark.parametrize(
    "cambios, campo",
    [
        ({"label": "  "}, "label"),
        ({"conf": 1.5}, "confidence"),
        ({"conf": -0.1}, "confidence"),
        ({"clase": -1}, "class_id"),
        ({"box": (10, 10, 5, 20)}, "box"),     # x2 < x1
        ({"box": (10, 10, 20, 10)}, "box"),    # sin alto
        ({"box": (-1, 0, 10, 10)}, "box"),     # fuera del frame
    ],
)
def test_c1_deteccion_invalida_se_rechaza(svc, run, cambios, campo):
    with pytest.raises(DetectionValidationError) as info:
        svc.save_event(evento(run, dets=[det(**cambios)]))
    assert info.value.field == campo


@pytest.mark.parametrize(
    "cambios, campo",
    [
        ({"seq": -1}, "frame_seq"),
        ({"frame_width": 640}, "frame_size"),  # alto sin ancho (height queda None)
    ],
)
def test_c1_evento_invalido_se_rechaza(svc, run, cambios, campo):
    with pytest.raises(DetectionValidationError) as info:
        svc.save_event(evento(run, **cambios))
    assert info.value.field == campo


def test_c1_fecha_sin_zona_horaria_se_rechaza(svc, run):
    malo = DetectionEventInput(
        run_id=run.id, frame_seq=1,
        captured_at=datetime(2026, 11, 1, 12, 0),  # sin tzinfo
        detections=[det()],
    )
    with pytest.raises(DetectionValidationError) as info:
        svc.save_event(malo)
    assert info.value.field == "captured_at"


def test_c1_procesado_antes_de_capturado_se_rechaza(svc, run):
    malo = DetectionEventInput(
        run_id=run.id, frame_seq=1,
        captured_at=T0 + timedelta(seconds=5),
        processed_at=T0 + timedelta(seconds=4),
        detections=[det()],
    )
    with pytest.raises(DetectionValidationError) as info:
        svc.save_event(malo)
    assert info.value.field == "processed_at"


# ── C2: los filtros producen resultados correctos ────────────────────────────

@pytest.fixture
def datos(db, svc):
    """Dos cámaras con eventos variados para probar los filtros."""
    cam_a = Camera(name="A", source="0", source_type=SourceType.USB)
    cam_b = Camera(name="B", source="1", source_type=SourceType.USB)
    run_a = ProcessingRun(camera=cam_a, kind=RunKind.INFERENCE_STREAM, model_id="m", created_at=T0)
    run_b = ProcessingRun(camera=cam_b, kind=RunKind.INFERENCE_STREAM, model_id="m", created_at=T0)
    run_a.start(at=T0)
    run_b.start(at=T0)
    db.add_all([cam_a, cam_b])
    db.flush()

    # Cámara A: 3 eventos a distintas horas, con distintas clases y confianzas
    svc.save_event(DetectionEventInput(
        run_id=run_a.id, frame_seq=1, captured_at=T0,
        detections=[det("pieza", 0.95, 1), det("tornillo", 0.60, 2)]))
    svc.save_event(DetectionEventInput(
        run_id=run_a.id, frame_seq=2, captured_at=T0 + timedelta(hours=1),
        detections=[det("tornillo", 0.80, 2)]))
    svc.save_event(DetectionEventInput(
        run_id=run_a.id, frame_seq=3, captured_at=T0 + timedelta(hours=2),
        detections=[det("pieza", 0.50, 1)]))
    # Cámara B: 1 evento
    svc.save_event(DetectionEventInput(
        run_id=run_b.id, frame_seq=1, captured_at=T0 + timedelta(minutes=30),
        detections=[det("pieza", 0.99, 1)]))
    return {"cam_a": cam_a.id, "cam_b": cam_b.id, "run_a": run_a.id, "run_b": run_b.id}


def test_c2_sin_filtros_devuelve_todo_ordenado_por_fecha(svc, datos):
    page = svc.query(EventQuery())
    assert page.total == 4
    fechas = [e.captured_at for e in page.events]
    assert fechas == sorted(fechas, reverse=True)  # más reciente primero


def test_c2_filtro_por_camara(svc, datos):
    page = svc.query(EventQuery(camera_id=datos["cam_a"]))
    assert page.total == 3
    assert all(e.camera_id == datos["cam_a"] for e in page.events)


def test_c2_filtro_por_clase(svc, datos):
    # class_id 2 (tornillo) aparece en 2 eventos de A
    page = svc.query(EventQuery(class_id=2))
    assert page.total == 2


def test_c2_filtro_por_etiqueta(svc, datos):
    page = svc.query(EventQuery(label="pieza"))
    assert page.total == 3  # dos de A, uno de B


def test_c2_filtro_por_confianza_minima(svc, datos):
    # confianza >= 0.9: evento 1 de A (0.95) y el de B (0.99)
    page = svc.query(EventQuery(min_confidence=0.9))
    assert page.total == 2


def test_c2_filtro_por_periodo(svc, datos):
    # [T0, T0+90min): evento de T0 (A, frame 1), T0+30min (B) y T0+1h (A, frame 2).
    # El de T0+2h (A, frame 3) queda fuera.
    page = svc.query(EventQuery(start=T0, end=T0 + timedelta(minutes=90)))
    assert page.total == 3

    # Fin exclusivo: [T0, T0+1h) deja fuera el evento que cae justo en T0+1h
    estrecho = svc.query(EventQuery(start=T0, end=T0 + timedelta(hours=1)))
    assert estrecho.total == 2


def test_c2_filtros_combinados(svc, datos):
    # Cámara A, clase tornillo, confianza >= 0.7 → solo el evento 2 (0.80)
    page = svc.query(EventQuery(camera_id=datos["cam_a"], class_id=2, min_confidence=0.7))
    assert page.total == 1
    assert page.events[0].frame_seq == 2


def test_c2_el_evento_filtrado_conserva_todas_sus_detecciones(svc, datos):
    # El evento 1 de A tiene una detección 0.95 y otra 0.60; al filtrar por
    # confianza >= 0.9, el evento aparece con AMBAS detecciones.
    page = svc.query(EventQuery(camera_id=datos["cam_a"], min_confidence=0.9))
    assert page.total == 1
    etiquetas = {d.label for d in page.events[0].detections}
    assert etiquetas == {"pieza", "tornillo"}


def test_c2_paginacion(svc, datos):
    primera = svc.query(EventQuery(limit=2, offset=0))
    segunda = svc.query(EventQuery(limit=2, offset=2))

    assert primera.total == segunda.total == 4
    assert len(primera.events) == 2 and primera.has_more is True
    assert len(segunda.events) == 2 and segunda.has_more is False
    # Sin traslapes entre páginas
    ids = {e.id for e in primera.events} | {e.id for e in segunda.events}
    assert len(ids) == 4


def test_c2_filtro_sin_resultados(svc, datos):
    page = svc.query(EventQuery(label="inexistente"))
    assert page.total == 0 and page.events == [] and page.has_more is False


@pytest.mark.parametrize(
    "cambios, campo",
    [
        ({"min_confidence": 1.5}, "min_confidence"),
        ({"limit": 0}, "limit"),
        ({"limit": 5000}, "limit"),
        ({"offset": -1}, "offset"),
    ],
)
def test_c2_parametros_de_consulta_invalidos(svc, cambios, campo):
    with pytest.raises(DetectionValidationError) as info:
        svc.query(EventQuery(**cambios))
    assert info.value.field == campo


def test_c2_periodo_invertido_se_rechaza(svc):
    with pytest.raises(DetectionValidationError) as info:
        svc.query(EventQuery(start=T0 + timedelta(hours=1), end=T0))
    assert info.value.field == "period"


# ── C3: integridad de relaciones ─────────────────────────────────────────────

def test_c3_la_camara_del_evento_se_toma_de_la_corrida(svc, run, db):
    # Aunque alguien quisiera forzar otra cámara, el servicio usa la de la corrida
    r = svc.save_event(evento(run))
    assert r.camera_id == run.camera_id


def test_c3_evento_de_una_corrida_inexistente_se_rechaza(svc):
    malo = DetectionEventInput(
        run_id="corrida-fantasma", frame_seq=1,
        captured_at=T0, detections=[det()],
    )
    with pytest.raises(RunNotFoundError) as info:
        svc.save_event(malo)
    assert info.value.code == "RUN_NOT_FOUND"


def test_c3_un_frame_no_puede_tener_dos_eventos_en_la_misma_corrida(svc, run):
    svc.save_event(evento(run, seq=5))
    with pytest.raises(DuplicateEventError) as info:
        svc.save_event(evento(run, seq=5))
    assert info.value.code == "EVENT_DUPLICATE"


def test_c3_las_detecciones_se_guardan_ligadas_al_evento(svc, run, db):
    r = svc.save_event(evento(run, dets=[det("pieza"), det("tornillo", clase=2)]))

    # Cada detección quedó ligada al evento correcto en la base
    detecciones = db.query(Detection).all()
    assert len(detecciones) == 2
    assert all(d.event_id == r.id for d in detecciones)


def test_c3_borrar_el_evento_borra_sus_detecciones(svc, run, db):
    r = svc.save_event(evento(run, dets=[det(), det(clase=2)]))

    db.delete(db.get(DetectionEvent, r.id))
    db.flush()

    assert db.query(Detection).count() == 0        # cascada
    assert db.query(ProcessingRun).count() == 1     # la corrida permanece


def test_c3_los_metadatos_del_frame_se_conservan(svc, run):
    r = svc.save_event(evento(
        run, frame_width=1280, frame_height=720,
        roi=[[100, 100], [500, 400]],
        dets=[det(attrs={"ocr_text": "LOTE-42"})],
    ))

    assert r.frame_size == [1280, 720]
    assert r.roi == [[100, 100], [500, 400]]
    assert r.detections[0].attributes == {"ocr_text": "LOTE-42"}
