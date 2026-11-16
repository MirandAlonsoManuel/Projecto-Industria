"""
Demostración reproducible de la administración de fuentes de video (J03).

Sobre una base SQLite en memoria, registra fuentes, las lista por estado, las
actualiza, deshabilita, habilita y retira, y muestra cómo se rechazan las
operaciones inválidas. No necesita cámara, modelos ni red.

Ejecutar desde la carpeta backend:
    python scripts/demo_j03_fuentes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base, create_db_engine  # noqa: E402
from app.db.models import CameraStatus, SourceType  # noqa: E402
from app.services.source_admin import SourceAdminService, SourceError  # noqa: E402
from app.services.source_schemas import (  # noqa: E402
    SourceCreate,
    SourceUpdate,
    SourceValidationError,
)


def titulo(texto: str) -> None:
    print(f"\n{'─' * 70}\n{texto}\n{'─' * 70}")


def mostrar(svc: SourceAdminService) -> None:
    for s in svc.list():
        cred = s.credential_ref or "—"
        print(f"  [{s.status:<8}] {s.name:<28} {s.source_type}:{s.source:<28} cred={cred}")


def intento(descripcion, accion) -> None:
    try:
        accion()
        print(f"  ✗ {descripcion}: ¡se aceptó! (no debería)")
    except (SourceError, SourceValidationError) as exc:
        campo = f" [{exc.field}]" if isinstance(exc, SourceValidationError) else f" [{exc.code}]"
        print(f"  ✓ {descripcion}{campo}\n      {exc}")


def main() -> None:
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        svc = SourceAdminService(db)

        titulo("1. Registro de tres fuentes")
        usb = svc.register(SourceCreate(name="Línea 1 - USB", source_type=SourceType.USB, source="0"))
        ip = svc.register(SourceCreate(
            name="Entrada - IP", source_type=SourceType.RTSP,
            source="rtsp://10.0.0.5:554/stream", credential_ref="CAMARA_ENTRADA_RTSP",
        ))
        archivo = svc.register(SourceCreate(
            name="Prueba - video", source_type=SourceType.FILE, source="C:/videos/linea1.mp4",
        ))
        mostrar(svc)
        print(f"\n  La cámara IP guarda credenciales por referencia: "
              f"has_credentials={ip.has_credentials}, ref={ip.credential_ref}")

        titulo("2. Actualizar, deshabilitar y habilitar")
        svc.update(usb.id, SourceUpdate(name="Línea 1 - USB (principal)"))
        svc.disable(usb.id)
        print("  Tras renombrar y deshabilitar la USB:")
        mostrar(svc)
        svc.enable(usb.id)
        print(f"\n  Habilitada de nuevo: {svc.get(usb.id).status}")

        titulo("3. Retirar: distinto de deshabilitar")
        svc.retire(archivo.id)
        print("  La fuente de archivo se retiró (no se borró):")
        mostrar(svc)
        liberada = svc.register(SourceCreate(
            name="Prueba - video", source_type=SourceType.FILE, source="C:/videos/linea1.mp4",
        ))
        print(f"\n  El nombre y la fuente quedaron libres: se registró otra con id {liberada.id[:8]}…")

        titulo("4. Operaciones inválidas")
        intento("Nombre duplicado", lambda: svc.register(
            SourceCreate(name="Entrada - IP", source_type=SourceType.USB, source="1")))
        intento("Credenciales dentro de la fuente", lambda: svc.register(
            SourceCreate(name="Mala", source_type=SourceType.RTSP,
                         source="rtsp://admin:clave@10.0.0.5/stream")))
        intento("Modificar una fuente retirada", lambda: svc.update(
            archivo.id, SourceUpdate(name="X")))
        intento("Fuente USB no numérica", lambda: svc.register(
            SourceCreate(name="Rara", source_type=SourceType.USB, source="camara")))

        titulo("5. Verificación: ninguna respuesta expone secretos")
        import json
        salidas = [s.to_dict() for s in svc.list()]
        print(f"  ¿Aparece 'clave' en alguna respuesta? {'SÍ ✗' if 'clave' in json.dumps(salidas) else 'No ✓'}")

    engine.dispose()


if __name__ == "__main__":
    main()
