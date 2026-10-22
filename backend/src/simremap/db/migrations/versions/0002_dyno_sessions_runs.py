"""dyno-bench: tabelas ``simulation_session`` e ``dyno_run`` (data-model 2.2 e 6.1).

Revision ID: 0002_dyno_sessions_runs
Revises: 0001_foundation_base
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_dyno_sessions_runs"
down_revision: str | None = "0001_foundation_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

PROFILE_IDS = "'oem-stage', 'ft-pro', 'm1-race', 'ht-elite'"
FUEL_IDS = "'e27', 'e100', 'podium', 'e0'"
SESSION_STATES = "'ready', 'running', 'engine_locked', 'closed'"
RUN_TYPES = "'baseline_pull', 'sweep_pull', 'steady_state_hold', 'multi_pull'"
RUN_STATES = "'idle', 'arming', 'running', 'coastdown', 'completed', 'aborted', 'engine_failed'"
ABORT_REASONS = (
    "'user_abort', 'egt_limit', 'severe_knock_protection', 'catastrophic_failure', "
    "'arming_timeout', 'session_closed', 'run_timeout', 'internal_error'"
)


def upgrade() -> None:
    op.create_table(
        "simulation_session",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("vehicle_id", sa.String(length=48), nullable=False),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("catalog_sha256", sa.String(length=64), nullable=False),
        sa.Column("calibration_id", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=16), server_default="oem-stage", nullable=False),
        sa.Column("fuel_id", sa.String(length=16), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("sim_hz", sa.Integer(), server_default=sa.text("1000"), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("config_json", JSON, nullable=False),
        sa.Column("state", sa.String(length=16), server_default="ready", nullable=False),
        sa.Column("baseline_run_id", sa.String(length=26), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"profile_id IN ({PROFILE_IDS})", name=op.f("ck_simulation_session_profile_id")
        ),
        sa.CheckConstraint(f"fuel_id IN ({FUEL_IDS})", name=op.f("ck_simulation_session_fuel_id")),
        sa.CheckConstraint(
            f"state IN ({SESSION_STATES})", name=op.f("ck_simulation_session_state")
        ),
        sa.CheckConstraint(
            "seed >= 0 AND seed <= 9223372036854775807",
            name=op.f("ck_simulation_session_seed_range"),
        ),
        sa.CheckConstraint(
            "sim_hz >= 100 AND sim_hz <= 1000", name=op.f("ck_simulation_session_sim_hz_range")
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_simulation_session")),
    )
    with op.batch_alter_table("simulation_session") as batch_op:
        batch_op.create_index(op.f("ix_simulation_session_vehicle_id"), ["vehicle_id"])
        batch_op.create_index(op.f("ix_simulation_session_state"), ["state"])
        batch_op.create_index(op.f("ix_simulation_session_attempt_id"), ["attempt_id"])

    op.create_table(
        "dyno_run",
        sa.Column("run_id", sa.String(length=26), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("run_type", sa.String(length=24), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="idle", nullable=False),
        sa.Column("abort_reason", sa.String(length=32), nullable=True),
        sa.Column("calibration_id", sa.String(length=64), nullable=False),
        sa.Column("calibration_hash", sa.String(length=64), nullable=False),
        sa.Column("request_json", JSON, nullable=False),
        sa.Column("summary_json", JSON, nullable=True),
        sa.Column("curve_raw_json", JSON, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("pulls_json", JSON, nullable=True),
        sa.Column("repeatability_json", JSON, nullable=True),
        sa.Column("curve_sha256", sa.String(length=64), nullable=True),
        sa.Column("started_at_tick", sa.BigInteger(), nullable=False),
        sa.Column("ended_at_tick", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"run_type IN ({RUN_TYPES})", name=op.f("ck_dyno_run_run_type")),
        sa.CheckConstraint(f"state IN ({RUN_STATES})", name=op.f("ck_dyno_run_state")),
        sa.CheckConstraint(
            f"abort_reason IN ({ABORT_REASONS})", name=op.f("ck_dyno_run_abort_reason")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_session.session_id"],
            name=op.f("fk_dyno_run_session_id_simulation_session"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_dyno_run")),
    )
    with op.batch_alter_table("dyno_run") as batch_op:
        batch_op.create_index(
            op.f("ix_dyno_run_session_id_created_at"), ["session_id", "created_at"]
        )
        batch_op.create_index(op.f("ix_dyno_run_curve_sha256"), ["curve_sha256"])


def downgrade() -> None:
    with op.batch_alter_table("dyno_run") as batch_op:
        batch_op.drop_index(op.f("ix_dyno_run_curve_sha256"))
        batch_op.drop_index(op.f("ix_dyno_run_session_id_created_at"))
    op.drop_table("dyno_run")
    with op.batch_alter_table("simulation_session") as batch_op:
        batch_op.drop_index(op.f("ix_simulation_session_attempt_id"))
        batch_op.drop_index(op.f("ix_simulation_session_state"))
        batch_op.drop_index(op.f("ix_simulation_session_vehicle_id"))
    op.drop_table("simulation_session")
