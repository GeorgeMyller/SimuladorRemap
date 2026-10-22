"""Tabelas do Modo Carreira (002 data-delta, migração ``0008_career``).

- ``career_profiles``: saldo (centavos, pode ficar negativo) e reputação 0–100 por perfil
  local de jogador (FK para ``player_profile.id``); nenhum outro dado pessoal.
- ``career_jobs``: ordem aceita, tentativa vinculada e deltas da liquidação. Além dos campos
  do data-delta guarda ``scenario_id`` e ``session_id`` da tentativa (resposta do aceite sem
  ler o ``attempt``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Index, func, text
from sqlmodel import Field, SQLModel

from simremap.career.contracts import INITIAL_BALANCE_BRL, INITIAL_REPUTATION, JobStatus
from simremap.db.base import UTCDateTime, utcnow
from simremap.db.models._columns import check_expr, check_in

__all__ = ["CareerJobRow", "CareerProfileRow"]


def _timestamp() -> Any:
    return Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": func.now(), "nullable": False},
    )


class CareerProfileRow(SQLModel, table=True):
    __tablename__ = "career_profiles"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_expr("reputation >= 0 AND reputation <= 100", "reputation_range"),
    )

    profile_id: str = Field(
        primary_key=True, max_length=36, foreign_key="player_profile.id", ondelete="RESTRICT"
    )
    balance_brl: int = Field(
        default=INITIAL_BALANCE_BRL,
        sa_column_kwargs={"server_default": text(str(INITIAL_BALANCE_BRL))},
    )
    reputation: int = Field(
        default=INITIAL_REPUTATION,
        sa_column_kwargs={"server_default": text(str(INITIAL_REPUTATION))},
    )
    created_at: datetime = _timestamp()
    updated_at: datetime = _timestamp()


class CareerJobRow(SQLModel, table=True):
    __tablename__ = "career_jobs"
    __table_args__: ClassVar[tuple[Any, ...]] = (
        check_in("status", JobStatus.values()),
        check_expr("payout_brl > 0 AND engine_cost_brl > 0", "amounts_positive"),
        Index("ix_career_jobs_profile_id_status", "profile_id", "status"),
    )

    job_id: str = Field(primary_key=True, max_length=36)
    profile_id: str = Field(
        max_length=36, foreign_key="career_profiles.profile_id", ondelete="RESTRICT"
    )
    order_id: str = Field(max_length=64)
    scenario_id: str = Field(max_length=64)
    attempt_id: str = Field(max_length=36, index=True)
    session_id: str | None = Field(default=None, max_length=36)
    status: str = Field(
        default="accepted", max_length=16, sa_column_kwargs={"server_default": "accepted"}
    )
    payout_brl: int
    engine_cost_brl: int
    delta_balance_brl: int | None = Field(default=None)
    delta_reputation: int | None = Field(default=None)
    accepted_at: datetime = _timestamp()
    settled_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
