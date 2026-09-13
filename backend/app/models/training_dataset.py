from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrainingDataset(Base):
    __tablename__ = "training_datasets"
    __table_args__ = (
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("row_version >= 1", name="positive_row_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": row_version}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingDatasetRevision(Base):
    __tablename__ = "training_dataset_revisions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "revision_number"),
        CheckConstraint("revision_number >= 1", name="positive_revision"),
        CheckConstraint(
            "length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="manifest_hash",
        ),
        CheckConstraint("json_valid(manifest) AND json_type(manifest)='object'", name="manifest"),
        CheckConstraint("json_valid(report) AND json_type(report)='object'", name="report"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("training_datasets.id", ondelete="RESTRICT"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingDatasetReview(Base):
    __tablename__ = "training_dataset_reviews"
    __table_args__ = (
        UniqueConstraint("revision_id", "sequence"),
        CheckConstraint("sequence >= 1", name="positive_sequence"),
        CheckConstraint(
            "status IN ('draft','pending_review','approved','rejected','revoked')", name="status"
        ),
        CheckConstraint("length(trim(reviewer)) BETWEEN 1 AND 200", name="reviewer"),
        CheckConstraint("length(trim(note)) BETWEEN 1 AND 2000", name="note"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("training_dataset_revisions.id", ondelete="RESTRICT"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    reviewer: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Shared schema is kept in both source editions; research services are not imported here.
for table, prefix, identity in (
    (
        cast(Table, TrainingDatasetRevision.__table__),
        "training_revision",
        "dataset_id,revision_number",
    ),
    (cast(Table, TrainingDatasetReview.__table__), "training_review", "revision_id,sequence"),
):
    for action in ("UPDATE", "DELETE"):
        event.listen(
            table,
            "after_create",
            DDL(  # type: ignore[no-untyped-call]
                f"CREATE TRIGGER {prefix}_no_{action.lower()} BEFORE {action} ON {table.name} "
                "BEGIN SELECT RAISE(ABORT, 'training audit records are immutable'); END"
            ).execute_if(dialect="sqlite"),
        )
    owner, sequence = identity.split(",")
    event.listen(
        table,
        "after_create",
        DDL(  # type: ignore[no-untyped-call]
            f"CREATE TRIGGER {prefix}_no_replace BEFORE INSERT ON {table.name} "
            f"WHEN EXISTS (SELECT 1 FROM {table.name} WHERE id=NEW.id OR "
            f"({owner}=NEW.{owner} AND {sequence}=NEW.{sequence})) "
            "BEGIN SELECT RAISE(ABORT, 'training audit records are immutable'); END"
        ).execute_if(dialect="sqlite"),
    )
