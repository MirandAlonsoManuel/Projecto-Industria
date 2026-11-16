"""
Base de la capa de persistencia (J01).

Aquí viven las piezas que todos los modelos comparten:

  - `Base`: clase declarativa de SQLAlchemy con una convención de nombres
    estable para restricciones e índices, para que las migraciones futuras
    generen siempre los mismos nombres.
  - `UTCDateTime`: tipo de columna que solo acepta fechas con zona horaria y
    las guarda en UTC. Una fecha "ingenua" (sin zona) se rechaza, porque no hay
    forma de saber a qué hora real corresponde.
  - `create_db_engine`: crea el motor y, en SQLite, activa la revisión de
    llaves foráneas, que SQLite trae apagada por defecto.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Engine, MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def new_id() -> str:
    """Identificador nuevo: UUID4 en texto (36 caracteres)."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """
    Fecha y hora siempre en UTC y siempre con zona horaria.

    Al guardar: rechaza fechas sin zona horaria y convierte las demás a UTC.
    Al leer: devuelve la fecha marcada como UTC, aunque el motor (SQLite) no
    conserve la zona.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Se esperaba datetime, se recibió {type(value).__name__}")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "La fecha no tiene zona horaria. Use fechas con zona, por ejemplo "
                "datetime.now(timezone.utc)."
            )
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def create_db_engine(url: str = "sqlite+pysqlite:///:memory:", **kwargs) -> Engine:
    """Crea el motor de base de datos con las llaves foráneas activas en SQLite."""
    engine = create_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
