from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrainingRun(Base):
    __tablename__ = "training_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_profile_id", "agent_revision_id"],
            ["agent_profile_revisions.agent_profile_id", "agent_profile_revisions.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('queued','running','cancelling','succeeded','failed',"
            "'cancelled','interrupted')",
            name="status",
        ),
        CheckConstraint("total_steps BETWEEN 1 AND 100", name="total_steps"),
        CheckConstraint("completed_steps BETWEEN 0 AND total_steps", name="completed_steps"),
        CheckConstraint("length(snapshot_sha256)=64", name="snapshot_hash"),
        CheckConstraint("length(request_sha256)=64", name="request_hash"),
        CheckConstraint("json_valid(snapshot) AND json_type(snapshot)='object'", name="snapshot"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    agent_profile_id: Mapped[UUID] = mapped_column(Uuid(), index=True)
    agent_revision_id: Mapped[UUID] = mapped_column(Uuid())
    dataset_revision_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("training_dataset_revisions.id", ondelete="RESTRICT"), index=True
    )
    retry_of: Mapped[UUID | None] = mapped_column(
        Uuid(), ForeignKey("training_runs.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    request_sha256: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default="queued", index=True
    )
    completed_steps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_steps: Mapped[int] = mapped_column(Integer)
    last_code: Mapped[str] = mapped_column(String(64), default="QUEUED", server_default="QUEUED")
    owner_token: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[float | None] = mapped_column(Float)
    finished_at: Mapped[float | None] = mapped_column(Float)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingEvent(Base):
    __tablename__ = "training_events"
    run_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("training_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    phase: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(64))
    completed_steps: Mapped[int] = mapped_column(Integer)
    total_steps: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingWorkerLease(Base):
    __tablename__ = "training_worker_leases"
    __table_args__ = (CheckConstraint("id=1", name="singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_token: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float, default=0, server_default="0")


EVENT_INSERT = (
    "INSERT INTO training_events (run_id,sequence,phase,code,completed"
    "_steps,total_steps) "
    "SELECT NEW.id,COALESCE(MAX(sequence),0)+1,NEW.status,NEW.last_code,"
    "NEW.completed_steps,NEW.total_steps FROM training_events WHERE run_id=NEW.id;"
)
TRIGGERS: dict[str, str] = {
    "training_run_identity": "BEFORE UPDATE ON training_runs WHEN "
    + " OR ".join(
        f"NEW.{column} IS NOT OLD.{column}"
        for column in (
            "id",
            "agent_profile_id",
            "agent_revision_id",
            "dataset_revision_id",
            "retry_of",
            "idempotency_key",
            "request_sha256",
            "snapshot",
            "snapshot_sha256",
            "total_steps",
            "created_at",
        )
    )
    + " BEGIN SELECT RAISE(ABORT, 'training run identity is immutable'); END",
    "training_run_state": (
        "BEFORE UPDATE ON training_runs WHEN "
        "OLD.status IN ('succeeded','failed','cancelled','interrupted') OR "
        "NEW.completed_steps < OLD.completed_steps OR "
        "(NEW.status='succeeded' AND NEW.completed_steps<>NEW.total_steps) OR "
        "(NEW.status<>OLD.status AND NOT ("
        "(OLD.status='queued' AND NEW.status IN ('running','cancelled')) OR "
        "(OLD.status='running' AND NEW.status IN ('cancelling','succeeded'"
        ",'failed','interrupted')) OR "
        "(OLD.status='cancelling' AND NEW.status='cancelled'))) "
        "BEGIN SELECT RAISE(ABORT, 'invalid training state transition'); END"
    ),
    "training_run_no_replace": (
        "BEFORE INSERT ON training_runs WHEN EXISTS (SELECT 1 FROM training_runs WHERE "
        "id=NEW.id OR idempotency_key=NEW.idempotency_key) "
        "BEGIN SELECT RAISE(ABORT, 'training runs cannot be replaced'); END"
    ),
    "training_run_no_delete": "BEFORE DELETE ON training_runs BEGIN SELECT RAISE(ABORT, 'trainin"
    "g runs are retained'); END",
    "training_run_created": "AFTER INSERT ON training_runs BEGIN " + EVENT_INSERT + " END",
    "training_run_changed": (
        "AFTER UPDATE ON training_runs WHEN NEW.status<>OLD.status OR "
        "NEW.completed_steps<>OLD.completed_steps BEGIN " + EVENT_INSERT + " END"
    ),
    "training_event_no_update": "BEFORE UPDATE ON training_events BEGIN SELECT RAISE(ABORT, 'train"
    "ing events are immutable'); END",
    "training_event_no_delete": "BEFORE DELETE ON training_events BEGIN SELECT RAISE(ABORT, 'train"
    "ing events are immutable'); END",
    "training_event_no_replace": (
        "BEFORE INSERT ON training_events WHEN EXISTS (SELECT 1 FROM training_events "
        "WHERE run_id=NEW.run_id AND sequence=NEW.sequence) "
        "BEGIN SELECT RAISE(ABORT, 'training events are immutable'); END"
    ),
}


def cancellation(code: str, condition: str) -> str:
    return (
        "UPDATE training_runs SET status=CASE WHEN status='queued' THEN 'c"
        "ancelled' ELSE 'cancelling' END, "
        f"last_code='{code}', finished_at=CASE WHEN status='queued' THEN unixepoch() ELSE NULL END "
        f"WHERE status IN ('queued','running') AND ({condition});"
    )


TRIGGERS["training_review_revoked"] = (
    "AFTER INSERT ON training_dataset_reviews WHEN NEW.status<>'approved' BEGIN "
    + cancellation("DATASET_REVOKED", "dataset_revision_id=NEW.revision_id")
    + " END"
)
TRIGGERS["training_agent_unavailable"] = (
    "AFTER UPDATE OF enabled,deleted_at ON agent_profiles WHEN NEW.ena"
    "bled=0 OR NEW.deleted_at IS NOT NULL BEGIN "
    + cancellation("AGENT_UNAVAILABLE", "agent_profile_id=NEW.id")
    + " END"
)
TRIGGERS["training_agent_scope_changed"] = (
    "AFTER INSERT ON agent_profile_revisions BEGIN "
    + cancellation(
        "SOURCE_SCOPE_REVOKED",
        "agent_profile_id=NEW.agent_profile_id AND EXISTS ("
        "SELECT 1 FROM json_each(training_runs.snapshot,'$.source_course_ids') AS source "
        "WHERE source.value NOT IN (SELECT value FROM json_each(NEW.config"
        ",'$.allowed_course_ids')))",
    )
    + " END"
)
TRIGGERS["training_course_deleted"] = (
    "AFTER DELETE ON courses BEGIN "
    + cancellation(
        "SOURCE_DELETED",
        "EXISTS (SELECT 1 FROM json_each(training_runs.snapshot,'$.source_course_ids') "
        "WHERE replace(value,'-','')=OLD.id)",
    )
    + " END"
)

for name, sql in TRIGGERS.items():
    event.listen(
        TrainingEvent.__table__,
        "after_create",
        DDL(f"CREATE TRIGGER IF NOT EXISTS {name} {sql}").execute_if(dialect="sqlite"),  # type: ignore[no-untyped-call]
    )
