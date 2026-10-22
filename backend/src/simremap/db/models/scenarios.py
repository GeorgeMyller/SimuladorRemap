"""Tabelas do training-scenarios (data-model 2.7, migração ``0007_scenarios_base``).

7 tabelas: ``player_profile``, ``scenario``, ``attempt``, ``attempt_run``,
``evaluation``, ``scenario_event`` e ``imported_package``.

- D-20: unicidade de nickname sem distinção de caixa pelo índice funcional
  ``uq_player_profile_nickname_lower`` em ``lower(nickname)``.
- D-12: ``attempt_run.pull_index`` ``NOT NULL`` com padrão 0; colunas ``run_type`` e
  ``peak_whp``.
- D-11: ``attempt.profile_id`` é o perfil de jogador (FK para ``player_profile.id``).
- Zero PII (7.3): ``scenario_event.data_json`` nunca leva nickname.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, Index, UniqueConstraint, false, func, text
from sqlmodel import Field, SQLModel

from simremap.db.base import UTCDateTime, utcnow
from simremap.db.models._columns import SEED_MAX, JSONType, check_expr, check_in
from simremap.scenarios.contracts import AttemptState, Role

__all__ = [
    "ATTEMPT_ORIGINS",
    "EVALUATION_STATUSES",
    "PACKAGE_KINDS",
    "REPLAY_STATUSES",
    "SCENARIO_KINDS",
    "SCENARIO_ORIGINS",
    "AttemptRow",
    "AttemptRunRow",
    "EvaluationRow",
    "ImportedPackageRow",
    "PlayerProfileRow",
    "ScenarioEventRow",
    "ScenarioRow",
]

SCENARIO_KINDS: tuple[str, ...] = ("base", "challenge")
SCENARIO_ORIGINS: tuple[str, ...] = ("builtin", "local", "imported")
ATTEMPT_ORIGINS: tuple[str, ...] = ("local", "imported")
REPLAY_STATUSES: tuple[str, ...] = (
    "not_run",
    "running",
    "verified",
    "mismatch",
    "incompatible_version",
)
EVALUATION_STATUSES: tuple[str, ...] = ("pending", "completed", "error")
PACKAGE_KINDS: tuple[str, ...] = ("challenge", "attempt")


def _created_at() -> Any:
    return Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )


class PlayerProfileRow(SQLModel, table=True):
    __tablename__ = "player_profile"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("role", Role.values()),
        Index("uq_player_profile_nickname_lower", func.lower(text("nickname")), unique=True),
    )

    id: str = Field(primary_key=True, max_length=36)
    nickname: str = Field(max_length=24)
    role: str = Field(
        default="student", max_length=16, sa_column_kwargs={"server_default": "student"}
    )
    created_at: datetime = _created_at()


class ScenarioRow(SQLModel, table=True):
    __tablename__ = "scenario"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("kind", SCENARIO_KINDS),
        check_in("origin", SCENARIO_ORIGINS),
    )

    id: str = Field(primary_key=True, max_length=64)
    kind: str = Field(max_length=16)
    builtin: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    origin: str = Field(
        default="local", max_length=16, sa_column_kwargs={"server_default": "local"}
    )
    scenario_sha256: str = Field(max_length=64, index=True)
    content_json: dict[str, Any] = Field(sa_type=JSONType)
    created_at: datetime = _created_at()


class AttemptRow(SQLModel, table=True):
    __tablename__ = "attempt"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("origin", ATTEMPT_ORIGINS),
        check_in("state", AttemptState.values()),
        check_in("replay_status", REPLAY_STATUSES),
        check_expr(f"seed >= 0 AND seed <= {SEED_MAX}", "seed_range"),
        check_expr("submissions >= 0", "submissions_non_negative"),
        check_expr("engine_restores >= 0", "engine_restores_non_negative"),
        UniqueConstraint("package_sha256", name="uq_attempt_package_sha256"),
        Index("ix_attempt_scenario_id_origin_started_at", "scenario_id", "origin", "started_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    scenario_id: str = Field(max_length=64, foreign_key="scenario.id", ondelete="RESTRICT")
    profile_id: str | None = Field(
        default=None,
        max_length=36,
        foreign_key="player_profile.id",
        ondelete="RESTRICT",
        index=True,
    )
    nickname: str = Field(max_length=24)
    origin: str = Field(
        default="local", max_length=16, sa_column_kwargs={"server_default": "local"}
    )
    state: str = Field(
        default="preparing", max_length=24, sa_column_kwargs={"server_default": "preparing"}
    )
    session_id: str | None = Field(default=None, max_length=36)
    calibration_id: str = Field(max_length=64)
    seed: int = Field(sa_type=BigInteger)
    baseline_run_id: str | None = Field(default=None, max_length=26)
    baseline_peak_whp: float | None = Field(default=None)
    submissions: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    hints_revealed_json: list[Any] = Field(
        default_factory=list,
        sa_type=JSONType,
        sa_column_kwargs={"server_default": text("'[]'"), "nullable": False},
    )
    engine_restores: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    producer_install_id: str | None = Field(default=None, max_length=36)
    package_sha256: str | None = Field(default=None, max_length=64)
    replay_status: str = Field(
        default="not_run", max_length=24, sa_column_kwargs={"server_default": "not_run"}
    )
    started_at: datetime = _created_at()
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow, "nullable": False},
    )


class AttemptRunRow(SQLModel, table=True):
    __tablename__ = "attempt_run"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_expr("pull_index >= 0", "pull_index_non_negative"),
    )

    attempt_id: str = Field(
        primary_key=True, max_length=36, foreign_key="attempt.id", ondelete="RESTRICT"
    )
    run_id: str = Field(primary_key=True, max_length=36)
    pull_index: int = Field(
        default=0,
        primary_key=True,
        sa_column_kwargs={"server_default": text("0"), "autoincrement": False},
    )
    run_type: str = Field(max_length=24)
    valid: bool
    invalid_reason: str | None = Field(default=None, max_length=48)
    calibration_hash: str | None = Field(default=None, max_length=64)
    peak_whp: float | None = Field(default=None)
    trace_json: dict[str, Any] = Field(sa_type=JSONType)  # EvaluationTrace + resumo da puxada


class EvaluationRow(SQLModel, table=True):
    __tablename__ = "evaluation"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        UniqueConstraint(
            "attempt_id", "submission_index", name="uq_evaluation_attempt_id_submission_index"
        ),
        check_expr("submission_index >= 1", "submission_index_min"),
        check_in("status", EVALUATION_STATUSES),
        check_expr("total_score >= 0 AND total_score <= 100", "total_score_range"),
    )

    id: str = Field(primary_key=True, max_length=36)
    attempt_id: str = Field(max_length=36, foreign_key="attempt.id", ondelete="RESTRICT")
    submission_index: int
    status: str = Field(
        default="pending", max_length=16, sa_column_kwargs={"server_default": "pending"}
    )
    passed: bool | None = Field(default=None)
    total_score: float | None = Field(default=None)
    result_json: dict[str, Any] = Field(sa_type=JSONType)
    evaluation_sha256: str | None = Field(default=None, max_length=64)
    evaluation_mismatch: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    created_at: datetime = _created_at()


class ScenarioEventRow(SQLModel, table=True):
    __tablename__ = "scenario_event"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        Index("ix_scenario_event_scenario_id_kind_created_at", "scenario_id", "kind", "created_at"),
    )

    id: str = Field(primary_key=True, max_length=36)
    kind: str = Field(max_length=32)
    scenario_id: str = Field(max_length=64)
    attempt_id: str = Field(max_length=36)
    data_json: dict[str, Any] = Field(sa_type=JSONType)
    created_at: datetime = _created_at()


class ImportedPackageRow(SQLModel, table=True):
    __tablename__ = "imported_package"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("kind", PACKAGE_KINDS),
        check_expr("size_bytes > 0", "size_bytes_positive"),
    )

    sha256: str = Field(primary_key=True, max_length=64)
    kind: str = Field(max_length=16)
    scenario_id: str = Field(max_length=64)
    attempt_id: str | None = Field(default=None, max_length=36)
    size_bytes: int
    imported_at: datetime = _created_at()
