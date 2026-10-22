"""Tabelas do ecu-profiles (data-model 2.5, migração ``0005_profiles_session_state``).

- ``ecu_session_state``: perfil e estado da ECU por sessão (fonte de verdade do perfil
  ativo, D-10). ``session_id`` é FK lógica para ``simulation_session``.
- ``ecu_base_setup_version``: versões imutáveis da ``BaseSetup`` (JSON canônico em
  ``Text``, D-08), com FK física para ``ecu_session_state`` (D-09).

``hardware_override_json`` guarda o ``HardwareOverride`` do training-scenarios e nunca
é exposto na API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Text, func
from sqlmodel import Field, SQLModel

from simremap.db.base import UTCDateTime, utcnow
from simremap.db.models._columns import ECU_PROFILE_IDS, check_expr, check_in

__all__ = ["ECU_STATES", "FEATURE_PACKAGES", "EcuBaseSetupVersionRow", "EcuSessionStateRow"]

ECU_STATES: tuple[str, ...] = ("oem", "awaiting_base_setup", "standalone_ready")
FEATURE_PACKAGES: tuple[str, ...] = ("base", "race")


class EcuSessionStateRow(SQLModel, table=True):
    __tablename__ = "ecu_session_state"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("profile_id", ECU_PROFILE_IDS),
        check_in("ecu_state", ECU_STATES),
        check_in("feature_package", FEATURE_PACKAGES),
    )

    session_id: str = Field(primary_key=True, max_length=36)
    profile_id: str = Field(max_length=16)
    ecu_state: str = Field(default="oem", max_length=24, sa_column_kwargs={"server_default": "oem"})
    feature_package: str = Field(
        default="base", max_length=8, sa_column_kwargs={"server_default": "base"}
    )
    oem_snapshot_calibration_id: str | None = Field(default=None, max_length=64)
    oem_snapshot_version: int | None = Field(default=None)
    standalone_calibration_id: str | None = Field(default=None, max_length=64)
    latest_base_setup_version: int | None = Field(default=None)
    hardware_override_json: str | None = Field(default=None, sa_type=Text)
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow, "nullable": False},
    )


class EcuBaseSetupVersionRow(SQLModel, table=True):
    __tablename__ = "ecu_base_setup_version"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_expr("version >= 1", "version_min"),
        check_in("profile_id", ECU_PROFILE_IDS),
    )

    session_id: str = Field(
        primary_key=True,
        max_length=36,
        foreign_key="ecu_session_state.session_id",
        ondelete="RESTRICT",
    )
    version: int = Field(primary_key=True, sa_column_kwargs={"autoincrement": False})
    profile_id: str = Field(max_length=16)
    payload_json: str = Field(sa_type=Text)
    setup_hash: str = Field(max_length=64, index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
