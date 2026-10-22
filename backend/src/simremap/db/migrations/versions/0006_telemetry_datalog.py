"""telemetry-datalogger: tabela ``datalog`` (data-model 2.6 e 6.1; D-01 do data-model).

Índices em ``run_id`` e ``vehicle_id`` e unicidade ``uq_datalog_sha256``.
O ``downgrade`` remove só a tabela: os arquivos em ``/data/logs`` ficam intactos (D-10);
nenhuma operação de sistema de arquivos corre nesta revisão.

Revision ID: 0006_telemetry_datalog
Revises: 0005_profiles_session_state
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_telemetry_datalog"
down_revision: str | None = "0005_profiles_session_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datalog",
        sa.Column("log_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=26), nullable=True),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("vehicle_id", sa.String(length=48), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("format_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("sim_hz", sa.Integer(), nullable=False),
        sa.Column("n_samples", sa.Integer(), nullable=False),
        sa.Column("n_channels", sa.Integer(), nullable=False),
        sa.Column("compressed_bytes", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("terminal_state", sa.String(length=16), nullable=False),
        sa.Column("truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("source", sa.String(length=16), server_default="simulated", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "sim_hz >= 100 AND sim_hz <= 1000", name=op.f("ck_datalog_sim_hz_range")
        ),
        sa.CheckConstraint("n_samples >= 0", name=op.f("ck_datalog_n_samples_non_negative")),
        sa.CheckConstraint(
            "n_channels >= 1 AND n_channels <= 256", name=op.f("ck_datalog_n_channels_range")
        ),
        sa.CheckConstraint(
            "terminal_state IN ('completed', 'aborted', 'engine_failed')",
            name=op.f("ck_datalog_terminal_state"),
        ),
        sa.CheckConstraint("source IN ('simulated', 'imported')", name=op.f("ck_datalog_source")),
        sa.PrimaryKeyConstraint("log_id", name=op.f("pk_datalog")),
        sa.UniqueConstraint("sha256", name=op.f("uq_datalog_sha256")),
    )
    op.create_index(op.f("ix_datalog_run_id"), "datalog", ["run_id"])
    op.create_index(op.f("ix_datalog_vehicle_id"), "datalog", ["vehicle_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_datalog_vehicle_id"), table_name="datalog")
    op.drop_index(op.f("ix_datalog_run_id"), table_name="datalog")
    op.drop_table("datalog")
