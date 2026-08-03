"""Add persisted course conversations and messages.

Revision ID: 20260803_03
Revises: 20260803_02
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_03"
down_revision: str | Sequence[str] | None = "20260803_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "course",
                "quick",
                name="conversation_kind",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="course",
            nullable=False,
        ),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=120), server_default="新课程对话", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_kind"), "conversations", ["kind"], unique=False)
    op.create_index(
        op.f("ix_conversations_course_id"),
        "conversations",
        ["course_id"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                name="message_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "completed",
                "pending",
                "failed",
                "interrupted",
                name="message_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="completed",
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("answer_status", sa.String(length=32), nullable=True),
        sa.Column("answer_style", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("retrieval", sa.JSON(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("elapsed_ms", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_messages_conversation_id_sequence_number",
        ),
    )
    op.create_index(
        op.f("ix_messages_conversation_id"),
        "messages",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_conversations_course_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_kind"), table_name="conversations")
    op.drop_table("conversations")
