"""Base declarativa partilhada (data-model 1.2, platform-foundation seção 9).

Todos os modelos de tabela herdam de ``sqlmodel.SQLModel`` com ``table=True`` e usam
o mesmo ``metadata`` (``SQLModel.metadata``), que recebe aqui a convenção de nomes
fixa de constraints. Importe este módulo ANTES de declarar qualquer tabela (o
``simremap.db.models`` já o faz).

Mixins:
- ``TimestampMixin``: ``created_at`` e ``updated_at`` em UTC (``server_default=now()``,
  ``onupdate``).
- ``UUIDPrimaryKeyMixin``: PK ``id`` ``String(36)`` com UUID4 em texto.

Tipos:
- ``UTCDateTime``: ``DateTime(timezone=True)`` que devolve sempre ``datetime`` com
  ``tzinfo=UTC`` (o SQLite não guarda fuso) e recusa ``datetime`` ingênuo na escrita.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel

__all__ = [
    "NAMING_CONVENTION",
    "TimestampMixin",
    "UTCDateTime",
    "UUIDPrimaryKeyMixin",
    "metadata",
    "new_uuid",
    "utcnow",
]

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata: MetaData = SQLModel.metadata
metadata.naming_convention = NAMING_CONVENTION


def utcnow() -> datetime:
    """Relógio de parede em UTC (só fora do laço físico)."""
    return datetime.now(UTC)


def new_uuid() -> str:
    """UUID4 em texto (36 caracteres)."""
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator[datetime]):
    """``DateTime(timezone=True)`` normalizado para UTC na escrita e na leitura."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime sem fuso horário: use datetime com tzinfo=UTC")
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"valor de data inesperado: {type(value).__name__}")
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class TimestampMixin(SQLModel):
    """Colunas ``created_at``/``updated_at`` em UTC preenchidas pelo servidor e pelo ORM."""

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow, "nullable": False},
    )


class UUIDPrimaryKeyMixin(SQLModel):
    """PK ``id`` em ``String(36)`` com UUID4 gerado no cliente."""

    id: str = Field(default_factory=new_uuid, primary_key=True, max_length=36)
