"""training-scenarios: 7 tabelas da seção 2.7 do data-model (6.1).

``player_profile`` (índice funcional único ``uq_player_profile_nickname_lower``, D-20),
``scenario``, ``attempt``, ``attempt_run`` (``pull_index`` NOT NULL padrão 0, D-12),
``evaluation``, ``scenario_event`` e ``imported_package``. Nenhuma FK para tabelas de
outros componentes (sessões, puxadas e calibrações são FKs lógicas). Os cenários base
são carregados no arranque, nunca nesta migração.

Revision ID: 0007_scenarios_base
Revises: 0006_telemetry_datalog
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_scenarios_base"
down_revision: str | None = "0006_telemetry_datalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

ATTEMPT_STATES = (
    "'preparing', 'in_progress', 'evaluating', 'passed', 'failed_final', 'abandoned', "
    "'expired', 'failed_to_start'"
)
REPLAY_STATUSES = "'not_run', 'running', 'verified', 'mismatch', 'incompatible_version'"


def _created_at(name: str = "created_at") -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "player_profile",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("nickname", sa.String(length=24), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="student", nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "role IN ('student', 'instructor')", name=op.f("ck_player_profile_role")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player_profile")),
    )
    op.create_index(
        "uq_player_profile_nickname_lower",
        "player_profile",
        [sa.text("lower(nickname)")],
        unique=True,
    )

    op.create_table(
        "scenario",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("builtin", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("origin", sa.String(length=16), server_default="local", nullable=False),
        sa.Column("scenario_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_json", JSON, nullable=False),
        _created_at(),
        sa.CheckConstraint("kind IN ('base', 'challenge')", name=op.f("ck_scenario_kind")),
        sa.CheckConstraint(
            "origin IN ('builtin', 'local', 'imported')", name=op.f("ck_scenario_origin")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario")),
    )
    op.create_index(op.f("ix_scenario_scenario_sha256"), "scenario", ["scenario_sha256"])

    op.create_table(
        "attempt",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=True),
        sa.Column("nickname", sa.String(length=24), nullable=False),
        sa.Column("origin", sa.String(length=16), server_default="local", nullable=False),
        sa.Column("state", sa.String(length=24), server_default="preparing", nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("calibration_id", sa.String(length=64), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("baseline_run_id", sa.String(length=26), nullable=True),
        sa.Column("baseline_peak_whp", sa.Float(), nullable=True),
        sa.Column("submissions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("hints_revealed_json", JSON, server_default=sa.text("'[]'"), nullable=False),
        sa.Column("engine_restores", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("producer_install_id", sa.String(length=36), nullable=True),
        sa.Column("package_sha256", sa.String(length=64), nullable=True),
        sa.Column("replay_status", sa.String(length=24), server_default="not_run", nullable=False),
        _created_at("started_at"),
        _created_at("updated_at"),
        sa.CheckConstraint("origin IN ('local', 'imported')", name=op.f("ck_attempt_origin")),
        sa.CheckConstraint(f"state IN ({ATTEMPT_STATES})", name=op.f("ck_attempt_state")),
        sa.CheckConstraint(
            f"replay_status IN ({REPLAY_STATUSES})", name=op.f("ck_attempt_replay_status")
        ),
        sa.CheckConstraint(
            "seed >= 0 AND seed <= 9223372036854775807", name=op.f("ck_attempt_seed_range")
        ),
        sa.CheckConstraint("submissions >= 0", name=op.f("ck_attempt_submissions_non_negative")),
        sa.CheckConstraint(
            "engine_restores >= 0", name=op.f("ck_attempt_engine_restores_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenario.id"],
            name=op.f("fk_attempt_scenario_id_scenario"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["player_profile.id"],
            name=op.f("fk_attempt_profile_id_player_profile"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempt")),
        sa.UniqueConstraint("package_sha256", name=op.f("uq_attempt_package_sha256")),
    )
    op.create_index(
        op.f("ix_attempt_scenario_id_origin_started_at"),
        "attempt",
        ["scenario_id", "origin", "started_at"],
    )
    op.create_index(op.f("ix_attempt_profile_id"), "attempt", ["profile_id"])

    op.create_table(
        "attempt_run",
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column(
            "pull_index",
            sa.Integer(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("run_type", sa.String(length=24), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("invalid_reason", sa.String(length=48), nullable=True),
        sa.Column("calibration_hash", sa.String(length=64), nullable=True),
        sa.Column("peak_whp", sa.Float(), nullable=True),
        sa.Column("trace_json", JSON, nullable=False),
        sa.CheckConstraint("pull_index >= 0", name=op.f("ck_attempt_run_pull_index_non_negative")),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempt.id"],
            name=op.f("fk_attempt_run_attempt_id_attempt"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("attempt_id", "run_id", "pull_index", name=op.f("pk_attempt_run")),
    )

    op.create_table(
        "evaluation",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("submission_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("result_json", JSON, nullable=False),
        sa.Column("evaluation_sha256", sa.String(length=64), nullable=True),
        sa.Column("evaluation_mismatch", sa.Boolean(), server_default=sa.false(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "submission_index >= 1", name=op.f("ck_evaluation_submission_index_min")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'error')", name=op.f("ck_evaluation_status")
        ),
        sa.CheckConstraint(
            "total_score >= 0 AND total_score <= 100", name=op.f("ck_evaluation_total_score_range")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempt.id"],
            name=op.f("fk_evaluation_attempt_id_attempt"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation")),
        sa.UniqueConstraint(
            "attempt_id",
            "submission_index",
            name=op.f("uq_evaluation_attempt_id_submission_index"),
        ),
    )

    op.create_table(
        "scenario_event",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("data_json", JSON, nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_event")),
    )
    op.create_index(
        op.f("ix_scenario_event_scenario_id_kind_created_at"),
        "scenario_event",
        ["scenario_id", "kind", "created_at"],
    )

    op.create_table(
        "imported_package",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        _created_at("imported_at"),
        sa.CheckConstraint(
            "kind IN ('challenge', 'attempt')", name=op.f("ck_imported_package_kind")
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_imported_package_size_bytes_positive")),
        sa.PrimaryKeyConstraint("sha256", name=op.f("pk_imported_package")),
    )


def downgrade() -> None:
    op.drop_table("imported_package")
    op.drop_index(
        op.f("ix_scenario_event_scenario_id_kind_created_at"), table_name="scenario_event"
    )
    op.drop_table("scenario_event")
    op.drop_table("evaluation")
    op.drop_table("attempt_run")
    op.drop_index(op.f("ix_attempt_profile_id"), table_name="attempt")
    op.drop_index(op.f("ix_attempt_scenario_id_origin_started_at"), table_name="attempt")
    op.drop_table("attempt")
    op.drop_index(op.f("ix_scenario_scenario_sha256"), table_name="scenario")
    op.drop_table("scenario")
    op.drop_index("uq_player_profile_nickname_lower", table_name="player_profile")
    op.drop_table("player_profile")
