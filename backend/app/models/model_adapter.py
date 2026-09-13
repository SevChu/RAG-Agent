from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DDL, JSON, CheckConstraint, DateTime, ForeignKey, String, Uuid, event, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ModelAdapter(Base):
    __tablename__ = "model_adapters"
    __table_args__ = (
        CheckConstraint("artifact_kind='simulated' AND deployable=0", name="simulated_only"),
        CheckConstraint("evaluation_status='not_evaluated'", name="not_evaluated"),
        CheckConstraint("length(manifest_sha256)=64", name="manifest_hash"),
        CheckConstraint("json_valid(manifest) AND json_type(manifest)='object'", name="manifest"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("training_runs.id", ondelete="RESTRICT"), unique=True
    )
    predecessor_id: Mapped[UUID | None] = mapped_column(
        Uuid(), ForeignKey("model_adapters.id", ondelete="RESTRICT")
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    artifact_kind: Mapped[str] = mapped_column(
        String(20), default="simulated", server_default="simulated"
    )
    deployable: Mapped[bool] = mapped_column(default=False, server_default="0")
    evaluation_status: Mapped[str] = mapped_column(
        String(24), default="not_evaluated", server_default="not_evaluated"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


TRIGGERS = {
    "adapter_identity": "BEFORE UPDATE ON model_adapters WHEN "
    + " OR ".join(
        f"NEW.{c} IS NOT OLD.{c}"
        for c in (
            "id",
            "run_id",
            "predecessor_id",
            "manifest",
            "manifest_sha256",
            "artifact_kind",
            "deployable",
            "evaluation_status",
            "created_at",
        )
    )
    + " OR OLD.archived_at IS NOT NULL OR NEW.archived_at IS NULL "
    "BEGIN SELECT RAISE(ABORT, 'adapter identity is immutable'); END",
    "adapter_no_replace": "BEFORE INSERT ON model_adapters WHEN EXISTS (SELECT 1 FROM "
    "model_adapters WHERE id=NEW.id OR run_id=NEW.run_id) BEGIN SELECT "
    "RAISE(ABORT, 'adapter already registered'); END",
    "adapter_no_delete": "BEFORE DELETE ON model_adapters BEGIN SELECT "
    "RAISE(ABORT, 'adapters are retained'); END",
    "adapter_success_only": "BEFORE INSERT ON model_adapters WHEN NOT EXISTS (SELECT 1 "
    "FROM training_runs WHERE id=NEW.run_id AND status='succeeded' AND "
    "json_extract(result,'$.artifact_kind')='simulated' AND "
    "json_extract(result,'$.deployable')=0) BEGIN SELECT "
    "RAISE(ABORT, 'adapter requires successful simulated run'); END",
}
for name, sql in TRIGGERS.items():
    event.listen(
        ModelAdapter.__table__,
        "after_create",
        DDL(f"CREATE TRIGGER IF NOT EXISTS {name} {sql}").execute_if(dialect="sqlite"),  # type: ignore[no-untyped-call]
    )
