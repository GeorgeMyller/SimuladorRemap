"""Tabelas do knock-and-failure-model (data-model 2.3, migração ``0003_damage_health_reports``).

- ``engine_health``: saúde 1:1 por sessão (escrita no fim de puxada, em falhas e em
  restaurações; nunca por tick).
- ``failure_event``: falhas só de inserção, com ``health_after`` (D-07).
- ``forensic_report``: 1 laudo por puxada.

FKs físicas ``RESTRICT`` para ``simulation_session`` e ``dyno_run`` (migração anterior).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, Index, UniqueConstraint, false, func, text
from sqlmodel import Field, SQLModel

from simremap.damage.contracts import FailureMechanism, FailureMode
from simremap.db.base import UTCDateTime, utcnow
from simremap.db.models._columns import JSONType, check_expr, check_in

__all__ = ["REPORT_KINDS", "EngineHealthRow", "FailureEventRow", "ForensicReportRow"]

REPORT_KINDS: tuple[str, ...] = ("failure", "near_miss")


class EngineHealthRow(SQLModel, table=True):
    __tablename__ = "engine_health"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_expr("restore_count >= 0", "restore_count_non_negative"),
    )

    session_id: str = Field(
        primary_key=True,
        max_length=36,
        foreign_key="simulation_session.session_id",
        ondelete="RESTRICT",
    )
    components_json: list[Any] = Field(sa_type=JSONType)
    engine_locked: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    restore_count: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    rod_weights_json: list[Any] = Field(sa_type=JSONType)
    updated_at_tick: int = Field(sa_type=BigInteger)
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow, "nullable": False},
    )


class FailureEventRow(SQLModel, table=True):
    __tablename__ = "failure_event"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_expr("tick >= 0", "tick_non_negative"),
        check_expr("t_sim_s >= 0", "t_sim_s_non_negative"),
        check_expr("cylinder >= 1 AND cylinder <= 8", "cylinder_range"),
        check_in("mode", FailureMode.values()),
        check_in("mechanism", FailureMechanism.values()),
        check_expr("health_after >= 0 AND health_after <= 1", "health_after_range"),
        Index("ix_failure_event_session_id_t_sim_s", "session_id", "t_sim_s"),
    )

    failure_event_id: str = Field(primary_key=True, max_length=26)
    session_id: str = Field(
        max_length=36, foreign_key="simulation_session.session_id", ondelete="RESTRICT"
    )
    run_id: str | None = Field(
        default=None,
        max_length=26,
        foreign_key="dyno_run.run_id",
        ondelete="RESTRICT",
        index=True,
    )
    tick: int = Field(sa_type=BigInteger)
    t_sim_s: float
    cylinder: int | None = Field(default=None)
    component_id: str = Field(max_length=16)
    mode: str = Field(max_length=24)
    mechanism: str = Field(max_length=32)
    catastrophic: bool
    simulated_only: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    health_after: float
    causal_json: dict[str, Any] = Field(sa_type=JSONType)


class ForensicReportRow(SQLModel, table=True):
    __tablename__ = "forensic_report"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        UniqueConstraint("run_id", name="uq_forensic_report_run_id"),
        check_in("report_kind", REPORT_KINDS),
    )

    report_id: str = Field(primary_key=True, max_length=26)
    run_id: str = Field(max_length=26, foreign_key="dyno_run.run_id", ondelete="RESTRICT")
    session_id: str = Field(
        max_length=36,
        foreign_key="simulation_session.session_id",
        ondelete="RESTRICT",
        index=True,
    )
    failure_event_id: str | None = Field(
        default=None,
        max_length=26,
        foreign_key="failure_event.failure_event_id",
        ondelete="RESTRICT",
    )
    report_kind: str = Field(max_length=16)
    report_json: dict[str, Any] = Field(sa_type=JSONType)
    report_sha256: str = Field(max_length=64)
    generator_version: str = Field(max_length=16)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )
