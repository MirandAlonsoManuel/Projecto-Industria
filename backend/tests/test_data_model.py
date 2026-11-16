"""
Pruebas del modelo de datos de cámaras, procesamiento y detecciones — J01.

Cada prueba usa una base SQLite en memoria, nueva y vacía. Varias pruebas
insertan con SQL directo, sin pasar por los modelos de Python, para comprobar
que la integridad la garantiza la propia base de datos y no solo el código.

Criterios cubiertos:
  C1  El modelo conserva integridad de identificadores, relaciones, fechas y estados.
  C2  Se documentan campos, restricciones e índices necesarios.
  C3  No se almacenan credenciales en campos destinados a respuesta o historial.

Ejecutar:
    cd backend
    python -m pytest tests/test_data_model.py -v
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db import (
    Base,
    Camera,
    CameraStatus,
    CredentialLeakError,
    Detection,
    DetectionEvent,
    InvalidTransitionError,
    ProcessingRun,
    RunKind,
    RunStatus,
    SourceType,
    create_db_engine,
    find_credential,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "J01-modelo-de-datos.md"
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    engine = create_db_engine()
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session


def camara(nombre: str = "Línea 1", fuente: str = "0", tipo: SourceType = SourceType.USB) -> Camera:
    return Camera(name=nombre, source=fuente, source_type=tipo)


def corrida_en_curso(db: Session, cam: Camera, kind: RunKind = RunKind.INFERENCE_STREAM) -> ProcessingRun:
    run = ProcessingRun(
        camera=cam,
        kind=kind,
        model_id=None if kind == RunKind.STREAM else "yolo26n-localization",
        parameters={"conf": 0.25, "iou": 0.45},
        created_at=T0,
    )
    run.start(at=T0 + timedelta(seconds=1))
    db.add(run)
    db.flush()
    return run


def evento(run: ProcessingRun, seq: int = 1, **kwargs) -> DetectionEvent:
    datos = dict(
        run=run,
        camera_id=run.camera_id,
        frame_seq=seq,
        captured_at=T0 + timedelta(seconds=2),
        processed_at=T0 + timedelta(seconds=2, milliseconds=40),
        frame_width=640,
        frame_height=480,
    )
    datos.update(kwargs)
    return DetectionEvent(**datos)


def deteccion(**kwargs) -> Detection:
    datos = dict(label="pieza", class_id=1, confidence=0.9, x1=10, y1=20, x2=110, y2=220)
    datos.update(kwargs)
    return Detection(**datos)


def falla_en_bd(db: Session, sql: str, params: dict) -> bool:
    """Inserta con SQL directo y dice si la base de datos lo rechazó."""
    try:
        with db.begin_nested():
            db.execute(text(sql), params)
        return False
    except IntegrityError:
        return True


# ── C1: identificadores ───────────────────────────────────────────────────────

def test_c1_ids_son_uuid_unicos_generados_por_el_modelo(db):
    camaras = [camara(f"Cámara {i}", str(i)) for i in range(5)]
    db.add_all(camaras)
    db.commit()

    ids = [c.id for c in camaras]
    assert len(set(ids)) == 5
    assert all(uuid.UUID(i).version == 4 for i in ids)


def test_c1_id_duplicado_se_rechaza(db):
    db.add(camara("A", "0"))
    db.commit()
    existente = db.scalars(select(Camera)).one().id

    assert falla_en_bd(
        db,
        "INSERT INTO cameras (id, name, source_type, source, status, created_at, updated_at) "
        "VALUES (:id, 'B', 'usb', '1', 'active', :t, :t)",
        {"id": existente, "t": "2026-11-01 12:00:00.000000"},
    )


def test_c1_nombre_y_fuente_de_camara_son_unicos(db):
    db.add(camara("Línea 1", "0"))
    db.commit()

    db.add(camara("Línea 1", "1"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(camara("Línea 2", "0"))
    with pytest.raises(IntegrityError):
        db.commit()


# ── C1: relaciones ────────────────────────────────────────────────────────────

def test_c1_relaciones_completas_camara_corrida_evento_deteccion(db):
    cam = camara()
    run = corrida_en_curso(db, cam)
    ev = evento(run)
    ev.detections = [deteccion(), deteccion(label="tornillo", class_id=2, confidence=0.7)]
    db.add(ev)
    db.commit()

    leida = db.scalars(select(Camera)).one()
    assert leida.runs[0].events[0].detections[1].label == "tornillo"
    assert leida.runs[0].events[0].camera_id == leida.id


def test_c1_corrida_con_camara_inexistente_se_rechaza(db):
    assert falla_en_bd(
        db,
        "INSERT INTO processing_runs (id, camera_id, kind, parameters, status, created_at, "
        "frames_processed) VALUES (:id, 'no-existe', 'stream', '{}', 'pending', :t, 0)",
        {"id": str(uuid.uuid4()), "t": "2026-11-01 12:00:00.000000"},
    )


def test_c1_evento_debe_coincidir_con_la_camara_de_su_corrida(db):
    cam_a, cam_b = camara("A", "0"), camara("B", "1")
    db.add_all([cam_a, cam_b])
    run = corrida_en_curso(db, cam_a)
    db.commit()

    # Con los modelos, la cámara del evento se toma de su corrida automáticamente
    ev = DetectionEvent(run=run, frame_seq=1, captured_at=T0 + timedelta(seconds=2))
    db.add(ev)
    db.commit()
    assert ev.camera_id == cam_a.id

    # Con SQL directo, la base rechaza un evento de la corrida de A con la cámara B
    assert falla_en_bd(
        db,
        "INSERT INTO detection_events (id, run_id, camera_id, frame_seq, captured_at, processed_at) "
        "VALUES (:id, :run, :cam, 2, :t, :t)",
        {"id": str(uuid.uuid4()), "run": run.id, "cam": cam_b.id, "t": "2026-11-01 12:00:02.000000"},
    )


def test_c1_un_frame_solo_tiene_un_evento_por_corrida(db):
    run = corrida_en_curso(db, camara())
    db.add_all([evento(run, seq=7), evento(run, seq=7)])
    with pytest.raises(IntegrityError):
        db.commit()


def test_c1_no_se_borra_una_camara_con_historial(db):
    cam = camara()
    corrida_en_curso(db, cam)
    db.commit()

    db.delete(cam)
    with pytest.raises(IntegrityError):
        db.commit()


def test_c1_borrar_una_corrida_borra_sus_eventos_y_detecciones(db, engine):
    run = corrida_en_curso(db, camara())
    ev = evento(run)
    ev.detections = [deteccion(), deteccion()]
    db.add(ev)
    db.commit()

    # Borrado directo en la base: la cascada la hace la llave foránea, no Python
    db.execute(text("DELETE FROM processing_runs WHERE id = :id"), {"id": run.id})
    db.commit()

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM detection_events")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM detections")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM cameras")).scalar() == 1


# ── C1: fechas ────────────────────────────────────────────────────────────────

def test_c1_fechas_sin_zona_horaria_se_rechazan(db):
    db.add(Camera(name="A", source="0", source_type=SourceType.USB,
                  created_at=datetime(2026, 11, 1, 12, 0)))
    with pytest.raises(StatementError, match="zona horaria"):
        db.commit()


def test_c1_fechas_se_guardan_en_utc_y_conservan_el_instante(db):
    guadalajara = timezone(timedelta(hours=-6))
    local = datetime(2026, 11, 1, 6, 0, tzinfo=guadalajara)
    db.add(Camera(name="A", source="0", source_type=SourceType.USB,
                  created_at=local, updated_at=local))
    db.commit()
    db.expire_all()

    leida = db.scalars(select(Camera)).one()
    assert leida.created_at.tzinfo == timezone.utc
    assert leida.created_at == local                 # mismo instante
    assert leida.created_at.hour == 12               # expresado en UTC


def test_c1_fin_antes_del_inicio_se_rechaza(db):
    run = corrida_en_curso(db, camara())
    run.complete(at=run.started_at - timedelta(seconds=1))
    with pytest.raises(IntegrityError):
        db.commit()


def test_c1_procesado_antes_de_capturado_se_rechaza(db):
    run = corrida_en_curso(db, camara())
    db.add(evento(run, captured_at=T0 + timedelta(seconds=5), processed_at=T0 + timedelta(seconds=4)))
    with pytest.raises(IntegrityError):
        db.commit()


def test_c1_updated_at_avanza_al_modificar(db):
    cam = Camera(name="A", source="0", source_type=SourceType.USB, created_at=T0, updated_at=T0)
    db.add(cam)
    db.commit()

    cam.status = CameraStatus.INACTIVE
    db.commit()

    assert cam.updated_at > T0


# ── C1: estados ───────────────────────────────────────────────────────────────

def test_c1_ciclo_de_estados_valido(db):
    run = ProcessingRun(camera=camara(), kind=RunKind.STREAM, created_at=T0)
    db.add(run)
    db.commit()
    assert run.status == RunStatus.PENDING and run.started_at is None

    run.start(at=T0 + timedelta(seconds=1))
    run.frames_processed = 120
    run.complete(at=T0 + timedelta(seconds=5))
    db.commit()

    assert run.status == RunStatus.COMPLETED
    assert run.finished_at > run.started_at


@pytest.mark.parametrize(
    "preparar, accion",
    [
        (lambda r: None, lambda r: r.complete()),                    # pendiente → completada
        (lambda r: None, lambda r: r.fail("X")),                     # pendiente → fallida
        (lambda r: (r.start(), r.complete()), lambda r: r.start()),  # completada → en curso
        (lambda r: r.cancel(), lambda r: r.start()),                 # cancelada → en curso
    ],
)
def test_c1_transiciones_invalidas_se_rechazan(preparar, accion):
    run = ProcessingRun(kind=RunKind.STREAM, status=RunStatus.PENDING)
    preparar(run)
    estado_previo = run.status
    with pytest.raises(InvalidTransitionError):
        accion(run)
    assert run.status == estado_previo


def test_c1_falla_guarda_codigo_y_mensaje(db):
    run = corrida_en_curso(db, camara())
    run.fail("CAMERA_STALLED", "La cámara dejó de producir frames.", at=T0 + timedelta(seconds=9))
    db.commit()

    assert run.status == RunStatus.FAILED
    assert run.error_code == "CAMERA_STALLED"


@pytest.mark.parametrize(
    "estado, inicio, fin, error, motivo",
    [
        ("completed", "2026-11-01 12:00:01.000000", None, None, "terminada sin fecha de fin"),
        ("running", None, None, None, "en curso sin fecha de inicio"),
        ("pending", None, "2026-11-01 12:00:05.000000", None, "pendiente con fecha de fin"),
        ("completed", "2026-11-01 12:00:01.000000", "2026-11-01 12:00:05.000000", "X", "error sin haber fallado"),
        ("failed", "2026-11-01 12:00:01.000000", "2026-11-01 12:00:05.000000", None, "fallida sin código"),
        ("archived", None, None, None, "estado que no existe"),
    ],
)
def test_c1_la_base_rechaza_estados_inconsistentes(db, estado, inicio, fin, error, motivo):
    db.add(camara())
    db.commit()
    cam_id = db.scalars(select(Camera)).one().id

    assert falla_en_bd(
        db,
        "INSERT INTO processing_runs (id, camera_id, kind, parameters, status, created_at, "
        "started_at, finished_at, frames_processed, error_code) "
        "VALUES (:id, :cam, 'stream', '{}', :estado, '2026-11-01 12:00:00.000000', "
        ":inicio, :fin, 0, :error)",
        {"id": str(uuid.uuid4()), "cam": cam_id, "estado": estado,
         "inicio": inicio, "fin": fin, "error": error},
    ), motivo


def test_c1_stream_sin_modelo_e_inferencia_con_modelo(db):
    cam = camara()
    db.add(ProcessingRun(camera=cam, kind=RunKind.STREAM, model_id="yolo", created_at=T0))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(ProcessingRun(camera=camara(), kind=RunKind.INFERENCE_STREAM, model_id=None, created_at=T0))
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.parametrize(
    "cambios",
    [
        {"confidence": 1.5},
        {"confidence": -0.1},
        {"x2": 10},             # caja sin ancho
        {"y1": -5},             # fuera del frame
        {"label": "   "},       # etiqueta vacía
        {"class_id": -1},
    ],
)
def test_c1_detecciones_invalidas_se_rechazan(db, cambios):
    run = corrida_en_curso(db, camara())
    ev = evento(run)
    ev.detections = [deteccion(**cambios)]
    db.add(ev)
    with pytest.raises(IntegrityError):
        db.commit()


# ── C3: sin credenciales en respuesta o historial ────────────────────────────

@pytest.mark.parametrize(
    "fuente",
    [
        "rtsp://admin:clave@10.0.0.5/stream",
        "rtsp://admin@10.0.0.5/stream",
        "rtsp://10.0.0.5/stream?user=admin&password=clave",
        "http://10.0.0.5/video?token=abc123",
    ],
)
def test_c3_la_fuente_de_una_camara_no_acepta_credenciales(fuente):
    with pytest.raises(CredentialLeakError):
        Camera(name="IP", source=fuente, source_type=SourceType.RTSP)


def test_c3_la_credencial_se_referencia_por_nombre(db):
    cam = Camera(
        name="Línea 3",
        source="rtsp://10.0.0.5:554/stream",
        source_type=SourceType.RTSP,
        credential_ref="CAMARA_LINEA3_RTSP",
    )
    db.add(cam)
    db.commit()
    assert cam.credential_ref == "CAMARA_LINEA3_RTSP"

    for valor in ("admin:clave123", "clave123", "rtsp://admin:clave@h"):
        with pytest.raises(ValueError):
            cam.credential_ref = valor


@pytest.mark.parametrize(
    "campo, valor",
    [
        ("parameters", {"conf": 0.25, "password": "clave"}),
        ("parameters", {"fuente": {"url": "rtsp://admin:clave@10.0.0.5/s"}}),
        ("parameters", {"headers": [{"Authorization": "Bearer abc"}]}),
        ("error_message", "No se pudo conectar a rtsp://admin:clave@10.0.0.5/s"),
    ],
)
def test_c3_la_corrida_no_acepta_credenciales(campo, valor):
    run = ProcessingRun(kind=RunKind.STREAM)
    with pytest.raises(CredentialLeakError):
        setattr(run, campo, valor)


def test_c3_los_atributos_de_una_deteccion_no_aceptan_credenciales():
    with pytest.raises(CredentialLeakError):
        deteccion(attributes={"ocr_text": "LOTE-42", "api_key": "xyz"})
    assert deteccion(attributes={"ocr_text": "LOTE-42"}).attributes == {"ocr_text": "LOTE-42"}


@pytest.mark.parametrize(
    "valor, limpio",
    [
        ("0", True),
        ("rtsp://10.0.0.5:554/stream", True),
        ({"conf": 0.3, "roi": [[0, 0], [10, 10]]}, True),
        ({"token_count": 3}, True),                     # nombre sensible, pero el valor es un número
        ({"auth": {"user": "a", "password": "b"}}, False),
        ("rtsp://u:p@h/s", False),
        ({"nested": {"secret": "s"}}, False),
        (["ok", "http://h/x?api_key=1"], False),
    ],
)
def test_c3_detector_de_credenciales(valor, limpio):
    assert (find_credential(valor) is None) is limpio


def test_c3_ninguna_tabla_termina_con_secretos(db, engine):
    """Escenario completo con una cámara IP: se recorre toda la base buscando secretos."""
    secreto = "Sup3rClave"
    cam = Camera(
        name="Cámara IP",
        source="rtsp://10.0.0.5:554/stream",
        source_type=SourceType.RTSP,
        credential_ref="CAMARA_IP_RTSP",
    )
    run = corrida_en_curso(db, cam)
    ev = evento(run)
    ev.detections = [deteccion(attributes={"ocr_text": "LOTE-42"})]
    db.add(ev)

    # Intentos de colar el secreto: todos se rechazan antes de llegar a la base
    for intento in (
        lambda: setattr(cam, "source", f"rtsp://admin:{secreto}@10.0.0.5:554/stream"),
        lambda: setattr(run, "parameters", {"password": secreto}),
        lambda: setattr(run, "error_message", f"falló rtsp://admin:{secreto}@10.0.0.5"),
    ):
        with pytest.raises(CredentialLeakError):
            intento()
    db.commit()

    with engine.connect() as conn:
        for tabla in Base.metadata.sorted_tables:
            filas = conn.execute(tabla.select()).mappings().all()
            assert secreto not in json.dumps([dict(f) for f in filas], default=str), tabla.name


# ── C2: documentación de campos, restricciones e índices ─────────────────────

def test_c2_la_documentacion_cubre_todos_los_campos_restricciones_e_indices(engine):
    """Si alguien agrega una columna o un índice sin documentarlo, esta prueba falla."""
    documento = DOC.read_text(encoding="utf-8")
    inspector = inspect(engine)
    faltantes = []

    for tabla in Base.metadata.sorted_tables:
        if f"`{tabla.name}`" not in documento:
            faltantes.append(tabla.name)
        for columna in tabla.columns:
            if not re.search(rf"`{columna.name}`", documento):
                faltantes.append(f"{tabla.name}.{columna.name}")
        for indice in inspector.get_indexes(tabla.name):
            if indice["name"] not in documento:
                faltantes.append(indice["name"])
        for restriccion in tabla.constraints:
            nombre = str(restriccion.name) if restriccion.name else ""
            if nombre and not nombre.startswith("pk_") and nombre not in documento:
                faltantes.append(nombre)

    assert faltantes == []
