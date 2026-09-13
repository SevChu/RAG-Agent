"""Training dataset identities, immutable revisions and append-only reviews.

Revision ID: 20260911_07
Revises: 20260910_06
This migration has no imports from mutable application models.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_07"
down_revision: str | Sequence[str] | None = "20260910_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_datasets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("name"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 100", name="name_length"),
        sa.CheckConstraint("row_version >= 1", name="positive_row_version"),
    )
    op.create_table(
        "training_dataset_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_id",
            sa.Uuid(),
            sa.ForeignKey("training_datasets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("dataset_id", "revision_number"),
        sa.CheckConstraint("revision_number >= 1", name="positive_revision"),
        sa.CheckConstraint(
            "length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="manifest_hash",
        ),
        sa.CheckConstraint(
            "json_valid(manifest) AND json_type(manifest)='object'", name="manifest"
        ),
        sa.CheckConstraint("json_valid(report) AND json_type(report)='object'", name="report"),
    )
    op.create_index(
        "ix_training_dataset_revisions_dataset_id", "training_dataset_revisions", ["dataset_id"]
    )
    op.create_table(
        "training_dataset_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("training_dataset_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=False),
        sa.Column("note", sa.String(2000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("revision_id", "sequence"),
        sa.CheckConstraint("sequence >= 1", name="positive_sequence"),
        sa.CheckConstraint(
            "status IN ('draft','pending_review','approved','rejected','revoked')", name="status"
        ),
        sa.CheckConstraint("length(trim(reviewer)) BETWEEN 1 AND 200", name="reviewer"),
        sa.CheckConstraint("length(trim(note)) BETWEEN 1 AND 2000", name="note"),
    )
    op.create_index(
        "ix_training_dataset_reviews_revision_id", "training_dataset_reviews", ["revision_id"]
    )
    for table, prefix, owner, number in (
        ("training_dataset_revisions", "training_revision", "dataset_id", "revision_number"),
        ("training_dataset_reviews", "training_review", "revision_id", "sequence"),
    ):
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {prefix}_no_{action.lower()} BEFORE {action} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'training audit records are immutable'); END"
            )
        op.execute(
            f"CREATE TRIGGER {prefix}_no_replace BEFORE INSERT ON {table} "
            f"WHEN EXISTS (SELECT 1 FROM {table} WHERE id=NEW.id OR "
            f"({owner}=NEW.{owner} AND {number}=NEW.{number})) "
            "BEGIN SELECT RAISE(ABORT, 'training audit records are immutable'); END"
        )


def downgrade() -> None:
    # Only registry metadata is removed. Raw files require separately reviewed cleanup.
    for table in ("training_dataset_reviews", "training_dataset_revisions", "training_datasets"):
        op.drop_table(table)
