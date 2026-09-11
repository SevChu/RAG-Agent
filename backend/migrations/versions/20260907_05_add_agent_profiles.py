"""Add immutable agent revisions and optional conversation bindings.

Revision ID: 20260907_05
Revises: 20260810_04
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_05"
down_revision: str | Sequence[str] | None = "20260810_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def require_safe_connection() -> None:
    # Rebuilding conversations with foreign_keys ON could cascade-delete messages.
    if op.get_bind().exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("agent migration requires an isolated FK-off Alembic connection")
    if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("foreign key validation failed before agent migration")


def check_foreign_keys() -> None:
    if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("foreign key validation failed after agent migration")


def upgrade() -> None:
    require_safe_connection()
    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("row_version >= 1", name="positive_row_version"),
        sa.Column(
            "enabled",
            sa.Boolean(create_constraint=True, name="enabled_boolean"),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 100", name="name_length"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "agent_profile_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_profile_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("config_sha256", sa.String(64), nullable=False),
        sa.Column("change_summary", sa.String(500), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["agent_profile_id"], ["agent_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_profile_id", "revision_number"),
        sa.UniqueConstraint("agent_profile_id", "id", name="uq_agent_revision_owner_id"),
        sa.CheckConstraint("revision_number >= 1", name="positive_revision"),
        sa.CheckConstraint(
            "length(config_sha256) = 64 AND config_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="config_sha256_format",
        ),
        sa.CheckConstraint(
            "json_valid(config) AND json_type(config) = 'object'", name="config_object"
        ),
    )
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("agent_profile_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("agent_profile_revision_id", sa.Uuid(), nullable=True))
        batch.create_check_constraint(
            "agent_binding_pair",
            "(agent_profile_id IS NULL AND agent_profile_revision_id IS NULL) OR "
            "(agent_profile_id IS NOT NULL AND agent_profile_revision_id IS NOT NULL)",
        )
        batch.create_foreign_key(
            "fk_conversations_agent_revision_owner",
            "agent_profile_revisions",
            ["agent_profile_id", "agent_profile_revision_id"],
            ["agent_profile_id", "id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_conversations_agent_profile_id", ["agent_profile_id"])
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER agent_revision_no_{action.lower()} "
            f"BEFORE {action} ON agent_profile_revisions "
            "BEGIN SELECT RAISE(ABORT, 'agent revisions are immutable'); END"
        )
    op.execute(
        "CREATE TRIGGER conversation_agent_binding_immutable "
        "BEFORE UPDATE OF agent_profile_id, agent_profile_revision_id ON conversations "
        "WHEN NEW.agent_profile_id IS NOT OLD.agent_profile_id "
        "OR NEW.agent_profile_revision_id IS NOT OLD.agent_profile_revision_id "
        "BEGIN SELECT RAISE(ABORT, 'conversation agent binding is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER agent_revision_no_replace BEFORE INSERT ON agent_profile_revisions "
        "WHEN EXISTS (SELECT 1 FROM agent_profile_revisions WHERE id=NEW.id OR "
        "(agent_profile_id=NEW.agent_profile_id AND revision_number=NEW.revision_number)) "
        "BEGIN SELECT RAISE(ABORT, 'agent revisions are immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER conversation_agent_no_replace BEFORE INSERT ON conversations "
        "WHEN EXISTS (SELECT 1 FROM conversations WHERE id=NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'conversation replacement is forbidden'); END"
    )
    check_foreign_keys()


def downgrade() -> None:
    require_safe_connection()
    op.execute("DROP TRIGGER conversation_agent_no_replace")
    op.execute("DROP TRIGGER conversation_agent_binding_immutable")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("fk_conversations_agent_revision_owner", type_="foreignkey")
        batch.drop_constraint(op.f("ck_conversations_agent_binding_pair"), type_="check")
        batch.drop_index("ix_conversations_agent_profile_id")
        batch.drop_column("agent_profile_revision_id")
        batch.drop_column("agent_profile_id")
    op.execute("DROP TRIGGER agent_revision_no_replace")
    op.execute("DROP TRIGGER agent_revision_no_update")
    op.execute("DROP TRIGGER agent_revision_no_delete")
    op.drop_table("agent_profile_revisions")
    op.drop_table("agent_profiles")
    check_foreign_keys()
