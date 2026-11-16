"""
Administración de fuentes de video (J03).

Reúne las operaciones de negocio sobre las cámaras registradas: registrar,
consultar, actualizar, habilitar y deshabilitar. Se apoya en el repositorio de
J02 y valida con los esquemas de J03, de modo que los routers (en una tarea
posterior) solo tengan que llamar a estos métodos.

Reglas que hace cumplir:
  - Identidad: no se repiten ni el nombre ni la fuente (tipo + valor).
  - Estado: habilitar/deshabilitar/retirar siguen transiciones claras; una
    fuente deshabilitada se distingue de una eliminada (se marca `retired`, no
    se borra, para conservar su historial).
  - Datos: cada campo se valida antes de guardar.
  - Credenciales: nada de lo que entra o sale las contiene.

El servicio no hace commit: trabaja sobre la sesión que recibe, igual que los
repositorios. Quien lo usa (session_scope o la dependencia de FastAPI) decide
cuándo confirmar.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Camera, CameraStatus, SourceType
from app.db.repositories import CameraRepository
from app.services.source_schemas import (
    SourceCreate,
    SourceRead,
    SourceUpdate,
    SourceValidationError,
    UNSET,
    _check_no_credentials,
    _validate_credential_ref,
    _validate_source_shape,
)


class SourceError(Exception):
    """Base de los errores de administración de fuentes, con un código estable."""

    code = "SOURCE_ERROR"


class SourceNotFoundError(SourceError):
    code = "SOURCE_NOT_FOUND"


class DuplicateSourceError(SourceError):
    code = "SOURCE_DUPLICATE"


class SourceStateError(SourceError):
    """La operación no aplica al estado actual de la fuente."""

    code = "SOURCE_INVALID_STATE"


class SourceAdminService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.cameras = CameraRepository(session)

    # ── Consultas ────────────────────────────────────────────────────────────

    def get(self, source_id: str) -> SourceRead:
        camera = self._require(source_id)
        return SourceRead.from_camera(camera)

    def list(self, *, status: Optional[CameraStatus] = None, include_retired: bool = True) -> list[SourceRead]:
        """
        Lista las fuentes. Por defecto incluye las retiradas, para que el
        historial sea visible; `include_retired=False` las oculta.
        """
        if status is not None:
            camaras = self.cameras.list_by_status(status)
        else:
            camaras = self.cameras.list()
            if not include_retired:
                camaras = [c for c in camaras if c.status != CameraStatus.RETIRED]
            camaras.sort(key=lambda c: c.name)
        return [SourceRead.from_camera(c) for c in camaras]

    # ── Registro ─────────────────────────────────────────────────────────────

    def register(self, data: SourceCreate) -> SourceRead:
        """Registra una fuente nueva, tras validar sus datos y su unicidad."""
        clean = data.validated()
        self._ensure_unique_name(clean.name)
        self._ensure_unique_source(clean.source_type, clean.source)

        camera = Camera(
            name=clean.name,
            source_type=clean.source_type,
            source=clean.source,
            credential_ref=clean.credential_ref,
            status=CameraStatus.ACTIVE,
        )
        self.cameras.add(camera)
        return SourceRead.from_camera(camera)

    # ── Actualización ────────────────────────────────────────────────────────

    def update(self, source_id: str, changes: SourceUpdate) -> SourceRead:
        """Actualiza nombre, fuente o referencia de credencial de una fuente."""
        camera = self._require(source_id)
        if camera.status == CameraStatus.RETIRED:
            raise SourceStateError("No se puede modificar una fuente retirada.")
        if not changes.has_changes():
            return SourceRead.from_camera(camera)

        if changes.name is not UNSET:
            nombre = changes.name.strip()
            if not nombre:
                raise SourceValidationError("name", "El nombre no puede estar vacío.")
            if nombre != camera.name:
                self._ensure_unique_name(nombre)
            camera.name = nombre

        # La fuente y su tipo se validan juntos: el tipo no cambia, pero la
        # forma de la fuente debe seguir correspondiéndole.
        if changes.source is not UNSET:
            _check_no_credentials("source", changes.source)
            nueva = _validate_source_shape(camera.source_type, changes.source)
            if nueva != camera.source:
                self._ensure_unique_source(camera.source_type, nueva)
            camera.source = nueva

        if changes.credential_ref is not UNSET:
            camera.credential_ref = _validate_credential_ref(changes.credential_ref)

        self.session.flush()
        return SourceRead.from_camera(camera)

    # ── Estado ───────────────────────────────────────────────────────────────

    def disable(self, source_id: str) -> SourceRead:
        """Deshabilita una fuente: queda registrada, pero fuera de servicio."""
        camera = self._require(source_id)
        if camera.status == CameraStatus.RETIRED:
            raise SourceStateError("Una fuente retirada no puede deshabilitarse.")
        camera.status = CameraStatus.INACTIVE
        self.session.flush()
        return SourceRead.from_camera(camera)

    def enable(self, source_id: str) -> SourceRead:
        """Vuelve a poner una fuente en servicio."""
        camera = self._require(source_id)
        if camera.status == CameraStatus.RETIRED:
            raise SourceStateError(
                "Una fuente retirada no puede habilitarse; regístrela de nuevo."
            )
        camera.status = CameraStatus.ACTIVE
        self.session.flush()
        return SourceRead.from_camera(camera)

    def retire(self, source_id: str) -> SourceRead:
        """
        Da de baja una fuente sin borrarla, para conservar su historial.

        Así se distingue "deshabilitada" (puede volver) de "eliminada"
        (retirada, definitiva). El nombre y la fuente quedan liberados para que
        puedan reutilizarse en un registro nuevo.
        """
        camera = self._require(source_id)
        if camera.status == CameraStatus.RETIRED:
            raise SourceStateError("La fuente ya estaba retirada.")
        camera.status = CameraStatus.RETIRED
        # Libera nombre y fuente sin perder el rastro de cuáles fueron
        camera.name = f"[retirada] {camera.name} ({camera.id[:8]})"
        camera.source = f"retired:{camera.id}"
        camera.credential_ref = None
        self.session.flush()
        return SourceRead.from_camera(camera)

    # ── Apoyo ────────────────────────────────────────────────────────────────

    def _require(self, source_id: str) -> Camera:
        camera = self.cameras.get(source_id)
        if camera is None:
            raise SourceNotFoundError(f"No existe una fuente con id '{source_id}'.")
        return camera

    def _ensure_unique_name(self, name: str) -> None:
        if self.cameras.get_by_name(name) is not None:
            raise DuplicateSourceError(f"Ya existe una fuente con el nombre '{name}'.")

    def _ensure_unique_source(self, source_type: SourceType, source: str) -> None:
        if self.cameras.get_by_source(source_type, source) is not None:
            raise DuplicateSourceError(
                f"Ya existe una fuente {source_type.value} con el valor '{source}'."
            )
