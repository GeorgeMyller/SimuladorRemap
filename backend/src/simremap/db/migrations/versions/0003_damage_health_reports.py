"""knock-and-failure-model: ``engine_health``, ``failure_event`` e ``forensic_report``.

Data-model 2.3 e 6.1. FKs ``RESTRICT`` para ``simulation_session`` e ``dyno_run``
(criadas em ``0002_dyno_sessions_runs``). O ``downgrade`` remove só estas 3 tabelas.

Revision ID: 0003_damage_health_reports
Revises: 0002_dyno_sessions_runs
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_damage_health_reports"
down_revision: str | None = "0002_dyno_sessions_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

FAILURE_MODES = (
    "'knock_damage', 'pre_ignition', 'egt_overtemp', 'rod_failure', 'piston_failure', "
    "'turbo_meltdown'"
)
FAILURE_MECHANISMS = (
    "'knock_erosion', 'ring_land_crack', 'head_gasket_breach', 'piston_thermal_melt', "
    "'valve_piston_contact', 'exhaust_valve_burn', 'rod_overload', 'rod_instant_bend', "
    "'bearing_spin', 'hot_spot_preignition', 'lspi', 'turbine_creep', 'turbo_overspeed_burst'"
)


def upgrade() -> None:
    op.create_table(
        "engine_health",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("components_json", JSON, nullable=False),
        sa.Column("engine_locked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("restore_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rod_weights_json", JSON, nullable=False),
        sa.Column("updated_at_tick", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "restore_count >= 0", name=op.f("ck_engine_health_restore_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_session.session_id"],
            name=op.f("fk_engine_health_session_id_simulation_session"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_engine_health")),
    )

    op.create_table(
        "failure_event",
        sa.Column("failure_event_id", sa.String(length=26), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=26), nullable=True),
        sa.Column("tick", sa.BigInteger(), nullable=False),
        sa.Column("t_sim_s", sa.Float(), nullable=False),
        sa.Column("cylinder", sa.Integer(), nullable=True),
        sa.Column("component_id", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("mechanism", sa.String(length=32), nullable=False),
        sa.Column("catastrophic", sa.Boolean(), nullable=False),
        sa.Column("simulated_only", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("health_after", sa.Float(), nullable=False),
        sa.Column("causal_json", JSON, nullable=False),
        sa.CheckConstraint("tick >= 0", name=op.f("ck_failure_event_tick_non_negative")),
        sa.CheckConstraint("t_sim_s >= 0", name=op.f("ck_failure_event_t_sim_s_non_negative")),
        sa.CheckConstraint(
            "cylinder >= 1 AND cylinder <= 8", name=op.f("ck_failure_event_cylinder_range")
        ),
        sa.CheckConstraint(f"mode IN ({FAILURE_MODES})", name=op.f("ck_failure_event_mode")),
        sa.CheckConstraint(
            f"mechanism IN ({FAILURE_MECHANISMS})", name=op.f("ck_failure_event_mechanism")
        ),
        sa.CheckConstraint(
            "health_after >= 0 AND health_after <= 1",
            name=op.f("ck_failure_event_health_after_range"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_session.session_id"],
            name=op.f("fk_failure_event_session_id_simulation_session"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["dyno_run.run_id"],
            name=op.f("fk_failure_event_run_id_dyno_run"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("failure_event_id", name=op.f("pk_failure_event")),
    )
    op.create_index(
        op.f("ix_failure_event_session_id_t_sim_s"), "failure_event", ["session_id", "t_sim_s"]
    )
    op.create_index(op.f("ix_failure_event_run_id"), "failure_event", ["run_id"])

    op.create_table(
        "forensic_report",
        sa.Column("report_id", sa.String(length=26), nullable=False),
        sa.Column("run_id", sa.String(length=26), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("failure_event_id", sa.String(length=26), nullable=True),
        sa.Column("report_kind", sa.String(length=16), nullable=False),
        sa.Column("report_json", JSON, nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("generator_version", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "report_kind IN ('failure', 'near_miss')", name=op.f("ck_forensic_report_report_kind")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["dyno_run.run_id"],
            name=op.f("fk_forensic_report_run_id_dyno_run"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["simulation_session.session_id"],
            name=op.f("fk_forensic_report_session_id_simulation_session"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["failure_event_id"],
            ["failure_event.failure_event_id"],
            name=op.f("fk_forensic_report_failure_event_id_failure_event"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("report_id", name=op.f("pk_forensic_report")),
        sa.UniqueConstraint("run_id", name=op.f("uq_forensic_report_run_id")),
    )
    op.create_index(op.f("ix_forensic_report_session_id"), "forensic_report", ["session_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_forensic_report_session_id"), table_name="forensic_report")
    op.drop_table("forensic_report")
    op.drop_index(op.f("ix_failure_event_run_id"), table_name="failure_event")
    op.drop_index(op.f("ix_failure_event_session_id_t_sim_s"), table_name="failure_event")
    op.drop_table("failure_event")
    op.drop_table("engine_health")
