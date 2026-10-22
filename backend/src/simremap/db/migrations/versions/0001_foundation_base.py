"""platform-foundation: tabela ``app_meta`` (data-model 2.1 e 6.1).

Revision ID: 0001_foundation_base
Revises: (base)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_foundation_base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=512), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_meta")),
    )


def downgrade() -> None:
    op.drop_table("app_meta")
