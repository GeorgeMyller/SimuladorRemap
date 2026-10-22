"""ecu-core: ``calibration``, ``calibration_version`` e ``session_calibration``.

Data-model 2.4 e 6.1. Índices em ``(vehicle_id, profile_id)`` e ``content_hash``.
``payload_json`` em ``Text`` (JSON canônico, D-08). Sem FK para tabelas de outros
componentes (``session_id`` é FK lógica).

Revision ID: 0004_ecu_calibrations
Revises: 0003_damage_health_reports
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_ecu_calibrations"
down_revision: str | None = "0003_damage_health_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_IDS = "'oem-stage', 'ft-pro', 'm1-race', 'ht-elite'"
SOURCES = "'user', 'wizard', 'oem_stock', 'import', 'clone', 'revert', 'reference'"


def upgrade() -> None:
    op.create_table(
        "calibration",
        sa.Column("calibration_id", sa.String(length=64), nullable=False),
        sa.Column("vehicle_id", sa.String(length=48), nullable=False),
        sa.Column("profile_id", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("latest_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"profile_id IN ({PROFILE_IDS})", name=op.f("ck_calibration_profile_id")
        ),
        sa.CheckConstraint("latest_version >= 1", name=op.f("ck_calibration_latest_version_min")),
        sa.PrimaryKeyConstraint("calibration_id", name=op.f("pk_calibration")),
    )
    op.create_index(
        op.f("ix_calibration_vehicle_id_profile_id"), "calibration", ["vehicle_id", "profile_id"]
    )

    op.create_table(
        "calibration_version",
        sa.Column("calibration_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("parent_version", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("author_nickname", sa.String(length=24), nullable=True),
        sa.Column("source", sa.String(length=16), server_default="user", nullable=False),
        sa.Column("change_summary", sa.String(length=200), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_calibration_version_version_min")),
        sa.CheckConstraint(
            "parent_version >= 1", name=op.f("ck_calibration_version_parent_version_min")
        ),
        sa.CheckConstraint(f"source IN ({SOURCES})", name=op.f("ck_calibration_version_source")),
        sa.ForeignKeyConstraint(
            ["calibration_id"],
            ["calibration.calibration_id"],
            name=op.f("fk_calibration_version_calibration_id_calibration"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("calibration_id", "version", name=op.f("pk_calibration_version")),
    )
    op.create_index(
        op.f("ix_calibration_version_content_hash"), "calibration_version", ["content_hash"]
    )

    op.create_table(
        "session_calibration",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("calibration_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("applied_t_sim_s", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["calibration_id", "version"],
            ["calibration_version.calibration_id", "calibration_version.version"],
            name=op.f("fk_session_calibration_calibration_id_calibration_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_session_calibration")),
    )


def downgrade() -> None:
    op.drop_table("session_calibration")
    op.drop_index(op.f("ix_calibration_version_content_hash"), table_name="calibration_version")
    op.drop_table("calibration_version")
    op.drop_index(op.f("ix_calibration_vehicle_id_profile_id"), table_name="calibration")
    op.drop_table("calibration")
