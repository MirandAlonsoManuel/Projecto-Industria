"""
Esquemas de entrada y salida para la administración de fuentes (J03).

Separan tres cosas que conviene no mezclar:

  - lo que llega para crear o actualizar una fuente (`SourceCreate`,
    `SourceUpdate`), que se valida antes de tocar la base;
  - lo que sale hacia el cliente (`SourceRead`), que nunca incluye
    credenciales;
  - un objeto `_Unset` para distinguir, en una actualización, "no toques este
    campo" de "ponlo en nulo".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from app.db.models import Camera, CameraStatus, SourceType

# Credenciales dentro de una URL o de un parámetro
_USERINFO = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s@]+@")
_SENSITIVE_QUERY = re.compile(
    r"[?&][a-zA-Z0-9_\-]*(pass(word|wd)?|pwd|token|secret|api[_-]?key|auth|credential|user(name)?)"
    r"[a-zA-Z0-9_\-]*=[^&\s]+",
    re.IGNORECASE,
)
_CREDENTIAL_REF = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_RTSP = re.compile(r"^rtsps?://", re.IGNORECASE)


class SourceValidationError(ValueError):
    """La fuente recibida no cumple las reglas de registro."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


# Centinela para "campo no provisto" en una actualización parcial
class _Unset:
    _instance: Optional["_Unset"] = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


def _check_no_credentials(field: str, value: Any) -> None:
    if isinstance(value, str) and (_USERINFO.search(value) or _SENSITIVE_QUERY.search(value)):
        raise SourceValidationError(
            field,
            "La fuente no debe incluir usuario ni contraseña. Guarda la URL pública "
            "y pon el nombre del secreto en credential_ref.",
        )


def _validate_source_shape(source_type: SourceType, source: str) -> str:
    source = source.strip()
    if not source:
        raise SourceValidationError("source", "La fuente no puede estar vacía.")

    if source_type == SourceType.USB:
        if not source.isdigit():
            raise SourceValidationError("source", "Una fuente USB es un índice, por ejemplo '0'.")
    elif source_type == SourceType.RTSP:
        if not _RTSP.match(source):
            raise SourceValidationError("source", "Una fuente RTSP debe empezar con rtsp:// o rtsps://.")
    # FILE: cualquier ruta no vacía es válida
    return source


def _validate_credential_ref(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _CREDENTIAL_REF.match(value):
        raise SourceValidationError(
            "credential_ref",
            "credential_ref es el NOMBRE de un secreto en mayúsculas (p. ej. "
            "CAMARA_LINEA1_RTSP), nunca la credencial misma.",
        )
    return value


@dataclass
class SourceCreate:
    """Datos para registrar una fuente nueva."""

    name: str
    source_type: SourceType
    source: str
    credential_ref: Optional[str] = None

    def validated(self) -> "SourceCreate":
        name = self.name.strip()
        if not name:
            raise SourceValidationError("name", "El nombre no puede estar vacío.")
        if not isinstance(self.source_type, SourceType):
            raise SourceValidationError("source_type", "Tipo de fuente no válido.")
        _check_no_credentials("source", self.source)
        source = _validate_source_shape(self.source_type, self.source)
        ref = _validate_credential_ref(self.credential_ref)
        return SourceCreate(name=name, source_type=self.source_type, source=source, credential_ref=ref)


@dataclass
class SourceUpdate:
    """
    Cambios para una fuente existente. Cada campo puede venir sin valor (UNSET)
    para dejarlo como está. `status` se cambia con habilitar/deshabilitar, no aquí.
    """

    name: Any = UNSET
    source: Any = UNSET
    credential_ref: Any = UNSET

    def has_changes(self) -> bool:
        return any(v is not UNSET for v in (self.name, self.source, self.credential_ref))


@dataclass
class SourceRead:
    """Vista pública de una fuente. Nunca incluye credenciales."""

    id: str
    name: str
    source_type: str
    source: str
    has_credentials: bool
    credential_ref: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_camera(cls, camera: Camera) -> "SourceRead":
        return cls(
            id=camera.id,
            name=camera.name,
            source_type=camera.source_type.value,
            source=camera.source,  # la base ya guarda solo la fuente pública
            has_credentials=camera.credential_ref is not None,
            credential_ref=camera.credential_ref,  # es un nombre, no un secreto
            status=camera.status.value,
            created_at=camera.created_at,
            updated_at=camera.updated_at,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "source_type": self.source_type,
            "source": self.source,
            "has_credentials": self.has_credentials,
            "credential_ref": self.credential_ref,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
