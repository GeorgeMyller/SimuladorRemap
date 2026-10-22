"""ecu-profiles: ``ecu_session_state`` e ``ecu_base_setup_version``.

Data-model 2.5 e 6.1. Índice em ``setup_hash``. ``session_id`` de ``ecu_session_state``
é FK lógica para ``simulation_session``; ``ecu_base_setup_version.session_id`` tem FK
física ``RESTRICT`` para ``ecu_session_state`` (D-09).

Revision ID: 0005_profiles_session_state
Revises: 0004_ecu_calibrations
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_profiles_session_state"
down_revision: str | None = "0004_ecu_calibrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_IDS = "'oem-stage', 'ft-pro', 'm1-race', 'ht-elite'"
ECU_STATES = "'oem', 'awaiting_base_setup', 'standalone_ready'"


def upgrade() -> None:
    op.create_table(
        "ecu_session_state",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=16), nullable=False),
        sa.Column("ecu_state", sa.String(length=24), server_default="oem", nullable=False),
        sa.Column("feature_package", sa.String(length=8), server_default="base", nullable=False),
        sa.Column("oem_snapshot_calibration_id", sa.String(length=64), nullable=True),
        sa.Column("oem_snapshot_version", sa.Integer(), nullable=True),
        sa.Column("standalone_calibration_id", sa.String(length=64), nullable=True),
        sa.Column("latest_base_setup_version", sa.Integer(), nullable=True),
        sa.Column("hardware_override_json", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"profile_id IN ({PROFILE_IDS})", name=op.f("ck_ecu_session_state_profile_id")
        ),
        sa.CheckConstraint(
            f"ecu_state IN ({ECU_STATES})", name=op.f("ck_ecu_session_state_ecu_state")
        ),
        sa.CheckConstraint(
            "feature_package IN ('base', 'race')",
            name=op.f("ck_ecu_session_state_feature_package"),
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_ecu_session_state")),
    )

    op.create_table(
        "ecu_base_setup_version",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("profile_id", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("setup_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_ecu_base_setup_version_version_min")),
        sa.CheckConstraint(
            f"profile_id IN ({PROFILE_IDS})", name=op.f("ck_ecu_base_setup_version_profile_id")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["ecu_session_state.session_id"],
            name=op.f("fk_ecu_base_setup_version_session_id_ecu_session_state"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", "version", name=op.f("pk_ecu_base_setup_version")),
    )
    op.create_index(
        op.f("ix_ecu_base_setup_version_setup_hash"), "ecu_base_setup_version", ["setup_hash"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ecu_base_setup_version_setup_hash"), table_name="ecu_base_setup_version")
    op.drop_table("ecu_base_setup_version")
    op.drop_table("ecu_session_state")
