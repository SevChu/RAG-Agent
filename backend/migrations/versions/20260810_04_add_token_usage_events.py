"""Add persistent per-model token usage events.

Revision ID: 20260810_04
Revises: 20260803_03
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_04"
down_revision: str | Sequence[str] | None = "20260803_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "token_usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("input_cache_hit_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_cache_miss_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_token_usage_events_model"),
        "token_usage_events",
        ["model"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_token_usage_events_model"), table_name="token_usage_events")
    op.drop_table("token_usage_events")
