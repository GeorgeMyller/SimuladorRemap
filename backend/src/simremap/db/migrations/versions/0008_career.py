"""Modo Carreira: ``career_profiles`` e ``career_jobs`` (002 data-delta; D-15).

``career_profiles`` guarda saldo (centavos, pode ficar negativo) e reputação 0–100 por perfil
local de jogador (FK para ``player_profile``). ``career_jobs`` liga a ordem aceita à
tentativa do cenário (FK lógica para ``attempt``) e guarda os deltas da liquidação.

Revision ID: 0008_career
Revises: 0007_scenarios_base
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_career"
down_revision: str | None = "0007_scenarios_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_STATUSES = "'accepted', 'paid', 'failed', 'engine_broken', 'abandoned'"


def _timestamp(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "career_profiles",
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("balance_brl", sa.Integer(), server_default=sa.text("500000"), nullable=False),
        sa.Column("reputation", sa.Integer(), server_default=sa.text("50"), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "reputation >= 0 AND reputation <= 100",
            name=op.f("ck_career_profiles_reputation_range"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["player_profile.id"],
            name=op.f("fk_career_profiles_profile_id_player_profile"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("profile_id", name=op.f("pk_career_profiles")),
    )
    op.create_table(
        "career_jobs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="accepted", nullable=False),
        sa.Column("payout_brl", sa.Integer(), nullable=False),
        sa.Column("engine_cost_brl", sa.Integer(), nullable=False),
        sa.Column("delta_balance_brl", sa.Integer(), nullable=True),
        sa.Column("delta_reputation", sa.Integer(), nullable=True),
        _timestamp("accepted_at"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN ({JOB_STATUSES})", name=op.f("ck_career_jobs_status")),
        sa.CheckConstraint(
            "payout_brl > 0 AND engine_cost_brl > 0",
            name=op.f("ck_career_jobs_amounts_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["career_profiles.profile_id"],
            name=op.f("fk_career_jobs_profile_id_career_profiles"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_career_jobs")),
    )
    op.create_index(op.f("ix_career_jobs_attempt_id"), "career_jobs", ["attempt_id"])
    op.create_index(
        op.f("ix_career_jobs_profile_id_status"), "career_jobs", ["profile_id", "status"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_career_jobs_profile_id_status"), table_name="career_jobs")
    op.drop_index(op.f("ix_career_jobs_attempt_id"), table_name="career_jobs")
    op.drop_table("career_jobs")
    op.drop_table("career_profiles")
