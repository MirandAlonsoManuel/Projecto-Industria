"""
Demostración reproducible del modelo de datos de J01.

Crea una base de datos en memoria, registra una cámara IP sin credenciales,
simula una corrida con eventos y detecciones, imprime el historial y luego
intenta varias operaciones inválidas para mostrar cómo se rechaza cada una.

No necesita cámara, modelos ni red.

Ejecutar desde la carpeta backend:
    python scripts/demo_j01_modelo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# La consola de Windows puede no usar UTF-8 al redirigir la salida a un archivo
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.exc import IntegrityError, StatementError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import (  # noqa: E402
    Base,
    Camera,
    CredentialLeakError,
    Detection,
    DetectionEvent,
    InvalidTransitionError,
    ProcessingRun,
    RunKind,
    SourceType,
    create_db_engine,
)

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def titulo(texto: str) -> None:
    print(f"\n{'─' * 70}\n{texto}\n{'─' * 70}")


def intento(descripcion: str, accion, session: Session) -> None:
    try:
        with session.begin_nested():
            accion()
            session.flush()
        print(f"  ✗ {descripcion}: ¡se aceptó! (no debería)")
    except IntegrityError as exc:
        detalle = str(exc.orig).splitlines()[0]
        print(f"  ✓ {descripcion}\n      rechazado por la base de datos: {detalle}")
    except StatementError as exc:
        detalle = str(exc.orig if exc.orig else exc).splitlines()[0]
        print(f"  ✓ {descripcion}\n      rechazado al preparar el guardado: {detalle}")
    except (CredentialLeakError, InvalidTransitionError, ValueError) as exc:
        print(f"  ✓ {descripcion}\n      rechazado por el modelo: {exc}")


def main() -> None:
    engine = create_db_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        titulo("1. Registro de una cámara IP sin credenciales")
        camara = Camera(
            name="Línea 1",
            source_type=SourceType.RTSP,
            source="rtsp://10.0.0.5:554/stream",
            credential_ref="CAMARA_LINEA1_RTSP",
        )
        db.add(camara)
        db.commit()
        print(f"  id:             {camara.id}")
        print(f"  fuente pública: {camara.source}")
        print(f"  credenciales:   en el secreto '{camara.credential_ref}', no en la base")

        titulo("2. Una corrida con inferencia, eventos y detecciones")
        run = ProcessingRun(
            camera=camara,
            kind=RunKind.INFERENCE_STREAM,
            model_id="yolo26n-localization",
            parameters={"conf": 0.25, "iou": 0.45, "infer_every_n_frames": 3},
            created_at=T0,
        )
        run.start(at=T0 + timedelta(seconds=1))
        for seq in range(1, 4):
            evento = DetectionEvent(
                run=run,
                frame_seq=seq * 3,
                captured_at=T0 + timedelta(seconds=1 + seq * 0.1),
                processed_at=T0 + timedelta(seconds=1 + seq * 0.1 + 0.04),
                frame_width=640,
                frame_height=480,
            )
            evento.detections = [
                Detection(label="pieza", class_id=1, confidence=0.91, x1=40, y1=60, x2=200, y2=260),
            ] if seq != 2 else []  # el frame 6 se procesó, pero sin detecciones
            db.add(evento)
        run.frames_processed = 9
        run.complete(at=T0 + timedelta(seconds=2))
        db.commit()

        print(f"  corrida {run.id[:8]}… estado={run.status.value} "
              f"duración={(run.finished_at - run.started_at).total_seconds():.1f} s")
        for ev in db.scalars(select(DetectionEvent).order_by(DetectionEvent.frame_seq)):
            resumen = ", ".join(f"{d.label} ({d.confidence:.0%})" for d in ev.detections) or "sin detecciones"
            print(f"    frame {ev.frame_seq:>2}  {ev.captured_at:%H:%M:%S.%f}"[:-3] + f"  → {resumen}")

        titulo("3. Operaciones inválidas")
        intento(
            "Fuente con usuario y contraseña",
            lambda: setattr(camara, "source", "rtsp://admin:clave@10.0.0.5:554/stream"),
            db,
        )
        intento(
            "Credencial real en credential_ref",
            lambda: setattr(camara, "credential_ref", "admin:clave"),
            db,
        )
        intento(
            "Contraseña dentro de los parámetros de una corrida",
            lambda: setattr(run, "parameters", {"password": "clave"}),
            db,
        )
        intento(
            "Reabrir una corrida ya completada",
            run.start,
            db,
        )
        intento(
            "Fecha sin zona horaria",
            lambda: db.add(Camera(name="X", source="9", source_type=SourceType.USB,
                                  created_at=datetime(2026, 11, 1, 12, 0))),
            db,
        )
        intento(
            "Confianza mayor a 1",
            lambda: db.add(Detection(event=evento, label="pieza", confidence=1.4,
                                     x1=0, y1=0, x2=10, y2=10)),
            db,
        )
        intento(
            "Borrar una cámara que tiene historial",
            lambda: db.delete(camara),
            db,
        )

        titulo("4. Verificación final")
        with engine.connect() as conn:
            for tabla in Base.metadata.sorted_tables:
                total = conn.execute(text(f"SELECT count(*) FROM {tabla.name}")).scalar()
                print(f"  {tabla.name:<18} {total} fila(s)")
            volcado = " ".join(
                str(fila) for tabla in Base.metadata.sorted_tables
                for fila in conn.execute(tabla.select())
            )
        print(f"\n  ¿Aparece la contraseña 'clave' en alguna tabla? {'SÍ ✗' if 'clave' in volcado else 'No ✓'}")


if __name__ == "__main__":
    main()
