"""
Pruebas de administración de fuentes de video — J03 (OMC...).

Cada prueba usa una base SQLite en memoria, nueva por caso, y trabaja a través
del servicio `SourceAdminService` sobre una sesión real, como lo haría la API.

Criterios cubiertos:
  C1  Las operaciones validan identidad, estado y datos de cada fuente.
  C2  Las fuentes deshabilitadas se distinguen de las eliminadas.
  C3  Las respuestas nunca exponen credenciales.

Ejecutar:
    cd backend
    python -m pytest tests/test_source_admin.py -v
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base, create_db_engine
from app.db.models import CameraStatus, SourceType
from app.services.source_admin import (
    DuplicateSourceError,
    SourceAdminService,
    SourceNotFoundError,
    SourceStateError,
)
from app.services.source_schemas import (
    SourceCreate,
    SourceUpdate,
    SourceValidationError,
)

SECRETO = "Sup3rClave"


@pytest.fixture
def db():
    engine = create_db_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def svc(db) -> SourceAdminService:
    return SourceAdminService(db)


def nueva(nombre="Línea 1", tipo=SourceType.USB, fuente="0", ref=None) -> SourceCreate:
    return SourceCreate(name=nombre, source_type=tipo, source=fuente, credential_ref=ref)


# ── C1: identidad, estado y datos ────────────────────────────────────────────

def test_c1_registro_valido_queda_activo(svc):
    r = svc.register(nueva("Entrada", SourceType.RTSP, "rtsp://10.0.0.5:554/stream", "CAM_ENTRADA"))

    assert r.status == CameraStatus.ACTIVE.value
    assert r.name == "Entrada"
    assert r.has_credentials is True
    assert svc.get(r.id).source == "rtsp://10.0.0.5:554/stream"


def test_c1_nombre_duplicado_se_rechaza(svc):
    svc.register(nueva("Línea 1", SourceType.USB, "0"))
    with pytest.raises(DuplicateSourceError) as info:
        svc.register(nueva("Línea 1", SourceType.USB, "1"))
    assert info.value.code == "SOURCE_DUPLICATE"


def test_c1_fuente_duplicada_se_rechaza(svc):
    svc.register(nueva("Línea 1", SourceType.USB, "0"))
    with pytest.raises(DuplicateSourceError):
        svc.register(nueva("Línea 2", SourceType.USB, "0"))


def test_c1_dos_tipos_pueden_compartir_el_mismo_valor(svc):
    # USB '0' y un archivo llamado '0' son fuentes distintas
    svc.register(nueva("USB", SourceType.USB, "0"))
    r = svc.register(nueva("Archivo", SourceType.FILE, "0"))
    assert r.source_type == "file"


@pytest.mark.parametrize(
    "tipo, fuente, campo",
    [
        (SourceType.USB, "camara", "source"),            # USB no numérico
        (SourceType.RTSP, "10.0.0.5/stream", "source"),  # RTSP sin esquema
        (SourceType.USB, "   ", "source"),               # vacío
    ],
)
def test_c1_fuente_mal_formada_se_rechaza(svc, tipo, fuente, campo):
    with pytest.raises(SourceValidationError) as info:
        svc.register(nueva("X", tipo, fuente))
    assert info.value.field == campo


def test_c1_nombre_vacio_se_rechaza(svc):
    with pytest.raises(SourceValidationError) as info:
        svc.register(nueva("   ", SourceType.USB, "0"))
    assert info.value.field == "name"


def test_c1_credential_ref_debe_ser_un_nombre_no_un_secreto(svc):
    for valor in ("admin:clave", "clave123", "minusculas"):
        with pytest.raises(SourceValidationError) as info:
            svc.register(nueva("X", SourceType.RTSP, "rtsp://h/s", ref=valor))
        assert info.value.field == "credential_ref"


def test_c1_operar_sobre_una_fuente_inexistente(svc):
    for accion in (svc.get, svc.disable, svc.enable, svc.retire):
        with pytest.raises(SourceNotFoundError):
            accion("no-existe")


def test_c1_actualizar_nombre_y_fuente(svc):
    r = svc.register(nueva("Vieja", SourceType.USB, "0"))
    actualizada = svc.update(r.id, SourceUpdate(name="Nueva", source="1"))

    assert actualizada.name == "Nueva"
    assert actualizada.source == "1"
    assert actualizada.updated_at >= actualizada.created_at


def test_c1_actualizar_parcial_respeta_lo_no_enviado(svc):
    r = svc.register(nueva("Original", SourceType.RTSP, "rtsp://h/s", "CAM_X"))
    # Solo se cambia el nombre; la fuente y la credencial quedan igual
    actualizada = svc.update(r.id, SourceUpdate(name="Renombrada"))

    assert actualizada.name == "Renombrada"
    assert actualizada.source == "rtsp://h/s"
    assert actualizada.credential_ref == "CAM_X"


def test_c1_actualizar_a_un_nombre_ya_usado_se_rechaza(svc):
    svc.register(nueva("Ocupado", SourceType.USB, "0"))
    otra = svc.register(nueva("Libre", SourceType.USB, "1"))
    with pytest.raises(DuplicateSourceError):
        svc.update(otra.id, SourceUpdate(name="Ocupado"))


def test_c1_actualizar_a_una_fuente_mal_formada_se_rechaza(svc):
    r = svc.register(nueva("RTSP", SourceType.RTSP, "rtsp://h/s"))
    with pytest.raises(SourceValidationError):
        svc.update(r.id, SourceUpdate(source="sin-esquema"))


def test_c1_quitar_la_credencial_con_cadena_vacia(svc):
    r = svc.register(nueva("Con ref", SourceType.RTSP, "rtsp://h/s", "CAM_X"))
    actualizada = svc.update(r.id, SourceUpdate(credential_ref=""))
    assert actualizada.has_credentials is False


# ── C2: deshabilitada ≠ eliminada ────────────────────────────────────────────

def test_c2_deshabilitar_conserva_la_fuente(svc):
    r = svc.register(nueva("Línea 1", SourceType.USB, "0"))
    deshabilitada = svc.disable(r.id)

    assert deshabilitada.status == CameraStatus.INACTIVE.value
    # Sigue existiendo y conserva sus datos
    assert svc.get(r.id).name == "Línea 1"
    assert svc.get(r.id).source == "0"


def test_c2_habilitar_regresa_al_servicio(svc):
    r = svc.register(nueva("Línea 1", SourceType.USB, "0"))
    svc.disable(r.id)
    habilitada = svc.enable(r.id)
    assert habilitada.status == CameraStatus.ACTIVE.value


def test_c2_retirar_no_borra_pero_distingue_de_deshabilitar(svc):
    r = svc.register(nueva("Línea 1", SourceType.USB, "0"))
    retirada = svc.retire(r.id)

    assert retirada.status == CameraStatus.RETIRED.value
    # Deshabilitada (inactive) y eliminada (retired) son estados distintos
    assert retirada.status != CameraStatus.INACTIVE.value
    # La fuente sigue consultable: no se borró
    assert svc.get(r.id).status == CameraStatus.RETIRED.value


def test_c2_una_fuente_retirada_libera_su_nombre_y_fuente(svc):
    r = svc.register(nueva("Línea 1", SourceType.USB, "0"))
    svc.retire(r.id)
    # El nombre y la fuente quedan libres para registrar una cámara nueva
    nueva_cam = svc.register(nueva("Línea 1", SourceType.USB, "0"))
    assert nueva_cam.status == CameraStatus.ACTIVE.value
    assert nueva_cam.id != r.id


def test_c2_una_fuente_retirada_no_se_modifica_ni_cambia_de_estado(svc):
    r = svc.register(nueva("Línea 1", SourceType.USB, "0"))
    svc.retire(r.id)
    for accion in (
        lambda: svc.update(r.id, SourceUpdate(name="X")),
        lambda: svc.enable(r.id),
        lambda: svc.disable(r.id),
        lambda: svc.retire(r.id),
    ):
        with pytest.raises(SourceStateError):
            accion()


def test_c2_el_listado_distingue_los_estados(svc):
    activa = svc.register(nueva("Activa", SourceType.USB, "0"))
    inactiva = svc.register(nueva("Inactiva", SourceType.USB, "1"))
    retirada = svc.register(nueva("Retirada", SourceType.USB, "2"))
    svc.disable(inactiva.id)
    svc.retire(retirada.id)

    todas = {s.status for s in svc.list()}
    assert todas == {"active", "inactive", "retired"}

    solo_activas = svc.list(status=CameraStatus.ACTIVE)
    assert [s.id for s in solo_activas] == [activa.id]

    sin_retiradas = svc.list(include_retired=False)
    assert all(s.status != "retired" for s in sin_retiradas)
    assert len(sin_retiradas) == 2


# ── C3: nunca se exponen credenciales ────────────────────────────────────────

@pytest.mark.parametrize(
    "fuente",
    [
        f"rtsp://admin:{SECRETO}@10.0.0.5/stream",
        f"rtsp://admin@10.0.0.5/stream",
        f"rtsp://10.0.0.5/stream?password={SECRETO}",
        f"rtsp://10.0.0.5/stream?token={SECRETO}",
    ],
)
def test_c3_registrar_con_credenciales_en_la_fuente_se_rechaza(svc, fuente):
    with pytest.raises(SourceValidationError) as info:
        svc.register(nueva("IP", SourceType.RTSP, fuente))
    assert info.value.field == "source"


def test_c3_actualizar_metiendo_credenciales_se_rechaza(svc):
    r = svc.register(nueva("IP", SourceType.RTSP, "rtsp://10.0.0.5/stream"))
    with pytest.raises(SourceValidationError):
        svc.update(r.id, SourceUpdate(source=f"rtsp://admin:{SECRETO}@10.0.0.5/stream"))


def test_c3_la_respuesta_no_incluye_la_credencial_solo_su_referencia(svc):
    r = svc.register(nueva("IP", SourceType.RTSP, "rtsp://10.0.0.5:554/stream", "CAMARA_IP_RTSP"))
    salida = r.to_dict()

    assert salida["has_credentials"] is True
    assert salida["credential_ref"] == "CAMARA_IP_RTSP"  # un nombre, no un secreto
    assert "password" not in salida
    assert SECRETO not in json.dumps(salida)


def test_c3_ninguna_respuesta_del_servicio_contiene_secretos(svc, db):
    """Escenario completo: registrar, actualizar, consultar y listar; nada filtra el secreto."""
    r = svc.register(nueva("IP", SourceType.RTSP, "rtsp://10.0.0.5:554/stream", "CAMARA_IP_RTSP"))
    svc.update(r.id, SourceUpdate(name="IP renombrada"))
    svc.disable(r.id)

    salidas = [svc.get(r.id).to_dict(), *(s.to_dict() for s in svc.list())]

    # Intento de filtración directo a la base, por si el servicio no fuera la única puerta
    with pytest.raises(SourceValidationError):
        svc.update(r.id, SourceUpdate(source=f"rtsp://x:{SECRETO}@h/s"))

    assert SECRETO not in json.dumps(salidas)
    # Y la fila en la base tampoco lo tiene
    from app.db.models import Camera
    fila = db.get(Camera, r.id)
    assert SECRETO not in f"{fila.source} {fila.credential_ref} {fila.name}"
