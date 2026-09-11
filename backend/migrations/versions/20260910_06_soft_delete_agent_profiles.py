"""Retain history while allowing agent profiles to leave the active catalog.

Revision ID: 20260910_06
Revises: 20260907_05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_06"
down_revision: str | Sequence[str] | None = "20260907_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_profiles", sa.Column("deleted_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    # Native SQLite DROP COLUMN avoids rebuilding a parent of immutable revisions.
    # Deleted profiles remain disabled; dropping this marker does not re-enable them.
    op.drop_column("agent_profiles", "deleted_at")
