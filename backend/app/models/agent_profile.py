from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.agents.configuration import AgentConfiguration
from app.db.base import Base


class AgentProfile(Base):
    __tablename__ = "agent_profiles"
    __table_args__ = (
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("row_version >= 1", name="positive_row_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean(create_constraint=True, name="enabled_boolean"),
        nullable=False,
        default=True,
        server_default="1",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    __mapper_args__ = {"version_id_col": row_version}

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentProfileRevision(Base):
    __tablename__ = "agent_profile_revisions"
    __table_args__ = (
        UniqueConstraint("agent_profile_id", "revision_number"),
        UniqueConstraint("agent_profile_id", "id", name="uq_agent_revision_owner_id"),
        CheckConstraint("revision_number >= 1", name="positive_revision"),
        CheckConstraint(
            "length(config_sha256) = 64 AND config_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="config_sha256_format",
        ),
        CheckConstraint(
            "json_valid(config) AND json_type(config) = 'object'", name="config_object"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    change_summary: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def read_config(self) -> AgentConfiguration:
        configuration = AgentConfiguration.model_validate(self.config)
        if configuration.sha256() != self.config_sha256:
            raise ValueError("agent revision configuration hash mismatch")
        return configuration


@event.listens_for(AgentProfileRevision, "before_insert")
def validate_revision(
    mapper: Mapper[AgentProfileRevision], connection: Connection, target: AgentProfileRevision
) -> None:
    configuration = AgentConfiguration.model_validate(target.config)
    digest = configuration.sha256()
    if target.config_sha256 is not None and target.config_sha256 != digest:
        raise ValueError("agent revision configuration hash mismatch")
    target.config = configuration.model_dump(mode="json")
    target.config_sha256 = digest


# SQLite triggers protect bulk SQL too. Frozen migration has its own DDL copy.
for action in ("UPDATE", "DELETE"):
    event.listen(
        AgentProfileRevision.__table__,
        "after_create",
        DDL(  # type: ignore[no-untyped-call]
            f"CREATE TRIGGER agent_revision_no_{action.lower()} "
            f"BEFORE {action} ON agent_profile_revisions "
            "BEGIN SELECT RAISE(ABORT, 'agent revisions are immutable'); END"
        ).execute_if(dialect="sqlite"),
    )

# REPLACE may bypass DELETE triggers when recursive_triggers is disabled.
event.listen(
    AgentProfileRevision.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "CREATE TRIGGER agent_revision_no_replace BEFORE INSERT ON agent_profile_revisions "
        "WHEN EXISTS (SELECT 1 FROM agent_profile_revisions WHERE id=NEW.id OR "
        "(agent_profile_id=NEW.agent_profile_id AND revision_number=NEW.revision_number)) "
        "BEGIN SELECT RAISE(ABORT, 'agent revisions are immutable'); END"
    ).execute_if(dialect="sqlite"),
)
