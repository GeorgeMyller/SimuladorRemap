"""Tabelas do dyno-bench: ``simulation_session`` e ``dyno_run`` (data-model 2.2).

Migração ``0002_dyno_sessions_runs``. Inclui as colunas das decisões D-05
(``data_version``, ``catalog_sha256``, ``fuel_id``, ``attempt_id``) e D-06
(``calibration_id``, ``repeatability_json``). FKs lógicas: ``vehicle_id`` (catálogo),
``attempt_id`` (tabela do Sprint 4) e ``baseline_run_id`` (evita ciclo).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, Index, func, text
from sqlmodel import Field, SQLModel

from simremap.db.base import UTCDateTime, utcnow
from simremap.db.models._columns import (
    ECU_PROFILE_IDS,
    FUEL_ID_VALUES,
    SEED_MAX,
    JSONType,
    check_expr,
    check_in,
)
from simremap.dyno.contracts import AbortReason, RunState, RunType

__all__ = ["SESSION_STATES", "DynoRunRow", "SimulationSessionRow"]

SESSION_STATES: tuple[str, ...] = ("ready", "running", "engine_locked", "closed")


class SimulationSessionRow(SQLModel, table=True):
    """Sessão de simulação; a linha nunca é apagada (``DELETE`` só fecha)."""

    __tablename__ = "simulation_session"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("profile_id", ECU_PROFILE_IDS),
        check_in("fuel_id", FUEL_ID_VALUES),
        check_in("state", SESSION_STATES),
        check_expr(f"seed >= 0 AND seed <= {SEED_MAX}", "seed_range"),
        check_expr("sim_hz >= 100 AND sim_hz <= 1000", "sim_hz_range"),
    )

    session_id: str = Field(primary_key=True, max_length=36)
    vehicle_id: str = Field(max_length=48, index=True)
    data_version: int
    catalog_sha256: str = Field(max_length=64)
    calibration_id: str = Field(max_length=64)
    profile_id: str = Field(
        default="oem-stage", max_length=16, sa_column_kwargs={"server_default": "oem-stage"}
    )
    fuel_id: str = Field(max_length=16)
    seed: int = Field(sa_type=BigInteger)
    sim_hz: int = Field(default=1000, sa_column_kwargs={"server_default": text("1000")})
    attempt_id: str | None = Field(default=None, max_length=36, index=True)
    config_json: dict[str, Any] = Field(sa_type=JSONType)
    state: str = Field(
        default="ready", max_length=16, index=True, sa_column_kwargs={"server_default": "ready"}
    )
    baseline_run_id: str | None = Field(default=None, max_length=26)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
    closed_at: datetime | None = Field(default=None, sa_type=UTCDateTime)


class DynoRunRow(SQLModel, table=True):
    """Puxada do dinamômetro; ``run_id`` é ULID e também o ``log_id`` do datalog."""

    __tablename__ = "dyno_run"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("run_type", RunType.values()),
        check_in("state", RunState.values()),
        check_in("abort_reason", AbortReason.values()),
        Index("ix_dyno_run_session_id_created_at", "session_id", "created_at"),
    )

    run_id: str = Field(primary_key=True, max_length=26)
    session_id: str = Field(
        max_length=36, foreign_key="simulation_session.session_id", ondelete="RESTRICT"
    )
    run_type: str = Field(max_length=24)
    state: str = Field(default="idle", max_length=16, sa_column_kwargs={"server_default": "idle"})
    abort_reason: str | None = Field(default=None, max_length=32)
    calibration_id: str = Field(max_length=64)
    calibration_hash: str = Field(max_length=64)
    request_json: dict[str, Any] = Field(sa_type=JSONType)
    summary_json: dict[str, Any] | None = Field(default=None, sa_type=JSONType)
    curve_raw_json: list[Any] = Field(
        default_factory=list,
        sa_type=JSONType,
        sa_column_kwargs={"server_default": text("'[]'"), "nullable": False},
    )
    pulls_json: list[Any] | None = Field(default=None, sa_type=JSONType)
    repeatability_json: dict[str, Any] | None = Field(default=None, sa_type=JSONType)
    curve_sha256: str | None = Field(default=None, max_length=64, index=True)
    started_at_tick: int = Field(sa_type=BigInteger)
    ended_at_tick: int | None = Field(default=None, sa_type=BigInteger)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
