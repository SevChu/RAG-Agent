from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import InvalidInputError, NotFoundError
from app.models import ModelAdapter, TrainingRun
from app.training.adapter_schemas import (
    AdapterManifest,
    AdapterRead,
    CompatibilityRead,
    CompatibilityRequest,
    SimulationResult,
)
from app.training.adapter_storage import AdapterStorage
from app.training.run_schemas import RunCreate
from app.training.validation import canonical, digest


class AdapterService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        if settings.agentic_edition != "research":
            raise HTTPException(status_code=403, detail="模拟产物仅在科研模式可用。")
        self.session = session
        self.settings = settings
        # Nested store keeps test/custom dataset roots isolated.
        self.storage = AdapterStorage(settings.training_data_dir / "adapters")

    async def _get(self, adapter_id: UUID) -> ModelAdapter:
        adapter = await self.session.get(ModelAdapter, adapter_id, populate_existing=True)
        if adapter is None:
            raise NotFoundError("模拟产物不存在。")
        return adapter

    @staticmethod
    def identity(run_id: UUID) -> UUID:
        return uuid5(NAMESPACE_URL, "agentic:simulated-adapter:" + run_id.hex)

    def read(self, adapter: ModelAdapter) -> AdapterRead:
        manifest = AdapterManifest.model_validate(adapter.manifest)
        status: Any = "valid"
        if (
            digest(canonical(adapter.manifest)) != adapter.manifest_sha256
            or manifest.adapter_id != adapter.id
            or manifest.run_id != adapter.run_id
            or manifest.predecessor_id != adapter.predecessor_id
        ):
            status = "invalid"
        else:
            try:
                if digest(self.storage.read(adapter.id)) != adapter.manifest_sha256:
                    status = "invalid"
            except FileNotFoundError:
                status = "missing"
            except (OSError, InvalidInputError):
                status = "invalid"
        return AdapterRead(
            id=adapter.id,
            run_id=adapter.run_id,
            predecessor_id=adapter.predecessor_id,
            manifest_sha256=adapter.manifest_sha256,
            integrity=status,
            created_at=adapter.created_at,
            archived_at=adapter.archived_at,
            manifest=manifest,
        )

    async def get(self, adapter_id: UUID) -> AdapterRead:
        return self.read(await self._get(adapter_id))

    async def list_adapters(
        self,
        limit: int,
        offset: int,
        agent_id: UUID | None,
        include_archived: bool,
    ) -> list[AdapterRead]:
        query = select(ModelAdapter).join(TrainingRun, ModelAdapter.run_id == TrainingRun.id)
        if agent_id is not None:
            query = query.where(TrainingRun.agent_profile_id == agent_id)
        if not include_archived:
            query = query.where(ModelAdapter.archived_at.is_(None))
        rows = await self.session.scalars(
            query.order_by(ModelAdapter.created_at.desc(), ModelAdapter.id)
            .limit(limit)
            .offset(offset)
        )
        return [self.read(row) for row in rows]

    async def predecessor(self, request: RunCreate) -> None:
        if request.predecessor_adapter_id is None:
            return
        adapter = await self._get(request.predecessor_adapter_id)
        item = self.read(adapter)
        source = item.manifest.source["request"]
        if (
            item.integrity != "valid"
            or adapter.archived_at is not None
            or source["agent_profile_id"] != str(request.agent_profile_id)
            or source["target"] != request.target
            or source["base_model"] != request.base_model
            or source["base_model_revision"] != request.base_model_revision
        ):
            raise InvalidInputError("前驱产物无效或与当前智能体/目标/基础模型不兼容。")

    async def register(self, run: TrainingRun) -> ModelAdapter:
        """Caller owns a fresh BEGIN IMMEDIATE transaction, including successful run update."""
        from app.training.run_store import RunStore
        from app.training.trainer import simulation_checksum

        if run.status != "succeeded" or run.finished_at is None:
            raise InvalidInputError("只有成功模拟任务可以登记产物。")
        try:
            snapshot = RunStore(self.session, self.settings)._parse(run)
            result = SimulationResult.model_validate(run.result)
        except ValueError as error:
            raise InvalidInputError("任务快照或模拟结果契约无效。") from error
        if result.simulation_checksum != simulation_checksum(snapshot):
            raise InvalidInputError("模拟结果校验失败。")
        adapter_id = self.identity(run.id)
        manifest = AdapterManifest(
            adapter_id=adapter_id,
            run_id=run.id,
            predecessor_id=snapshot.request.predecessor_adapter_id,
            run_snapshot_sha256=run.snapshot_sha256,
            source=RunStore.read(run).source,
            finished_at=run.finished_at,
            result=result,
        ).model_dump(mode="json")
        data = canonical(manifest)
        existing = await self.session.scalar(
            select(ModelAdapter).where(ModelAdapter.run_id == run.id)
        )
        if existing is not None:
            if existing.manifest != manifest or self.read(existing).integrity != "valid":
                raise InvalidInputError("已登记产物失效，不能自动覆盖或重建。")
            return existing
        try:
            self.storage.promote(adapter_id, data)
        except OSError as error:
            raise InvalidInputError("无法保存模拟产物，请检查存储空间与目录权限。") from error
        adapter = ModelAdapter(
            id=adapter_id,
            run_id=run.id,
            predecessor_id=snapshot.request.predecessor_adapter_id,
            manifest=manifest,
            manifest_sha256=digest(data),
        )
        self.session.add(adapter)
        await self.session.flush()
        return adapter

    async def reconcile(self, run_id: UUID) -> AdapterRead:
        from app.training.run_store import RunStore

        async with RunStore(self.session, self.settings).transaction():
            run = await self.session.get(TrainingRun, run_id)
            if run is None:
                raise NotFoundError("模拟训练任务不存在。")
            adapter = await self.register(run)
            return self.read(adapter)

    async def archive(self, adapter_id: UUID) -> AdapterRead:
        from app.training.run_store import RunStore

        async with RunStore(self.session, self.settings).transaction():
            adapter = await self._get(adapter_id)
            if adapter.archived_at is None:
                adapter.archived_at = datetime.now(UTC)
                await self.session.flush()
            return self.read(adapter)

    async def lineage(self, adapter_id: UUID, limit: int = 50) -> dict[str, Any]:
        items: list[AdapterRead] = []
        next_id: UUID | None = adapter_id
        while next_id is not None and len(items) < limit:
            item = await self.get(next_id)
            items.append(item)
            next_id = item.predecessor_id
        return {"items": items, "next_predecessor_id": next_id}

    async def compatibility(
        self, adapter_id: UUID, request: CompatibilityRequest
    ) -> CompatibilityRead:
        item = await self.get(adapter_id)
        source = item.manifest.source["request"]
        reasons = []
        for key in ("target", "base_model", "base_model_revision"):
            if source[key] != getattr(request, key):
                reasons.append(key.upper() + "_MISMATCH")
        if request.dataset_schema_version != item.manifest.dataset_schema_version:
            reasons.append("DATASET_SCHEMA_MISMATCH")
        if source["parameters"] != request.parameters.model_dump(mode="json"):
            reasons.append("PARAMETERS_MISMATCH")
        if item.integrity != "valid":
            reasons.append("ARTIFACT_INVALID")
        if item.archived_at is not None:
            reasons.append("ARTIFACT_ARCHIVED")
        return CompatibilityRead(
            contract_compatible=not reasons,
            reasons=[*reasons, "SIMULATED_NOT_DEPLOYABLE", "NOT_EVALUATED"],
        )

    async def inventory(self, offset: int, limit: int) -> dict[str, Any]:
        try:
            finals, staged, unknown, truncated = self.storage.inventory()
        except OSError as error:
            raise InvalidInputError("无法核对产物目录，请检查目录权限。") from error
        ids = finals[offset : offset + limit]
        registered = set(
            await self.session.scalars(select(ModelAdapter.id).where(ModelAdapter.id.in_(ids)))
        )
        return {
            "unregistered_file_ids": [i for i in ids if i not in registered],
            "scanned_final_files": len(finals),
            "staged_files": staged,
            "unknown_entries": unknown,
            "scan_truncated": truncated,
            "next_offset": offset + limit if offset + limit < len(finals) else None,
        }
