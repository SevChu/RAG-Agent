"""Add persisted document indexing progress.

Revision ID: 20260803_02
Revises: 20260730_01
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_02"
down_revision: str | Sequence[str] | None = "20260730_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "documents",
        sa.Column(
            "processing_stage",
            sa.Enum(
                "waiting",
                "preparing",
                "parsing",
                "chunking",
                "embedding",
                "storing",
                "completed",
                "failed",
                name="document_processing_stage",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="waiting",
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("progress_detail", sa.String(length=255), nullable=True),
    )

    op.execute(
        """
        UPDATE documents
        SET progress_percent = CASE WHEN status = 'completed' THEN 100 ELSE 0 END,
            processing_stage = CASE
                WHEN status = 'completed' THEN 'completed'
                WHEN status = 'failed' THEN 'failed'
                ELSE 'waiting'
            END,
            progress_detail = CASE
                WHEN status = 'completed' THEN '处理完成'
                WHEN status = 'failed' THEN '处理失败'
                ELSE '等待后台处理'
            END
        """
    )


def downgrade() -> None:
    op.drop_column("documents", "progress_detail")
    op.drop_column("documents", "processing_stage")
    op.drop_column("documents", "progress_percent")
