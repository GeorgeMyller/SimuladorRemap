"""Modelos da fundação: ``app_meta`` (data-model 2.1, migração ``0001_foundation_base``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Field, SQLModel

from simremap.db.base import UTCDateTime, utcnow

__all__ = ["APP_META_KEYS", "AppMeta"]

APP_META_KEYS: tuple[str, ...] = ("install_id", "schema_created_at", "last_boot_app_version")


class AppMeta(SQLModel, table=True):
    """Par chave/valor de metadados da instalação (sem PII; ``install_id`` é UUID4 local)."""

    __tablename__ = "app_meta"

    key: str = Field(primary_key=True, max_length=64)
    value: str = Field(max_length=512)
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow, "nullable": False},
    )
