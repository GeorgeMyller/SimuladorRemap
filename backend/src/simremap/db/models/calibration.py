"""Tabelas do ecu-core (data-model 2.4, migração ``0004_ecu_calibrations``).

- ``calibration``: cabeçalho com ``latest_version`` (concorrência otimista).
- ``calibration_version``: versões imutáveis; ``payload_json`` em ``Text`` com JSON
  canônico (D-08) para preservar os bytes do ``content_hash``.
- ``session_calibration``: calibração ativa por sessão (fonte de verdade, D-10), com FK
  composta para ``calibration_version`` (D-09). ``session_id`` é FK lógica.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import ForeignKeyConstraint, Index, Text, func, text
from sqlmodel import Field, SQLModel

from simremap.db.base import UTCDateTime, utcnow
from simremap.db.models._columns import ECU_PROFILE_IDS, check_expr, check_in

__all__ = [
    "CALIBRATION_SOURCES",
    "CalibrationRow",
    "CalibrationVersionRow",
    "SessionCalibrationRow",
]

CALIBRATION_SOURCES: tuple[str, ...] = (
    "user",
    "wizard",
    "oem_stock",
    "import",
    "clone",
    "revert",
    "reference",
)


class CalibrationRow(SQLModel, table=True):
    __tablename__ = "calibration"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("profile_id", ECU_PROFILE_IDS),
        check_expr("latest_version >= 1", "latest_version_min"),
        Index("ix_calibration_vehicle_id_profile_id", "vehicle_id", "profile_id"),
    )

    calibration_id: str = Field(primary_key=True, max_length=64)
    vehicle_id: str = Field(max_length=48)
    profile_id: str = Field(max_length=16)
    name: str = Field(max_length=80)
    latest_version: int = Field(default=1, sa_column_kwargs={"server_default": text("1")})
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


class CalibrationVersionRow(SQLModel, table=True):
    __tablename__ = "calibration_version"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_expr("version >= 1", "version_min"),
        check_expr("parent_version >= 1", "parent_version_min"),
        check_in("source", CALIBRATION_SOURCES),
    )

    calibration_id: str = Field(
        primary_key=True,
        max_length=64,
        foreign_key="calibration.calibration_id",
        ondelete="RESTRICT",
    )
    version: int = Field(primary_key=True, sa_column_kwargs={"autoincrement": False})
    parent_version: int | None = Field(default=None)
    content_hash: str = Field(max_length=64, index=True)
    payload_json: str = Field(sa_type=Text)
    author_nickname: str | None = Field(default=None, max_length=24)
    source: str = Field(default="user", max_length=16, sa_column_kwargs={"server_default": "user"})
    change_summary: str = Field(default="", max_length=200, sa_column_kwargs={"server_default": ""})
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )


class SessionCalibrationRow(SQLModel, table=True):
    __tablename__ = "session_calibration"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        ForeignKeyConstraint(
            ["calibration_id", "version"],
            ["calibration_version.calibration_id", "calibration_version.version"],
            ondelete="RESTRICT",
            name="fk_session_calibration_calibration_id_calibration_version",
        ),
    )

    session_id: str = Field(primary_key=True, max_length=36)
    calibration_id: str = Field(max_length=64)
    version: int
    content_hash: str = Field(max_length=64)
    applied_t_sim_s: float
