from __future__ import annotations

import hashlib
import platform
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import AgentProfileRevision, TrainingEvent, TrainingRun, TrainingWorkerLease
from app.training.run_schemas import EventRead, RunCreate, RunRead, RunSnapshot
from app.training.service import DatasetService
from app.training.validation import canonical, digest

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def code_identity() -> str:
    root = Path(__file__).parent
    files = sorted(root.glob("*.py")) + [
        root.parent / "models" / name
        for name in ("training_dataset.py", "training_run.py", "model_adapter.py")
    ]
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.name.encode() + b"\0" + path.read_bytes())
    return hasher.hexdigest()


class RunStore:
    def __init__(
        self, session: AsyncSession, settings: Settings, clock: Callable[[], float] = time.time
    ) -> None:
        if settings.agentic_edition != "research":
            raise HTTPException(status_code=403, detail="模拟训练任务仅在科研模式可用。")
        self.session = session
        self.settings = settings
        self.clock = clock

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        # A fresh session per mutation; serializes admission with revocation writes in SQLite.
        if self.session.in_transaction():
            raise ConflictError("任务操作需使用独立事务。")
        try:
            await self.session.execute(text("BEGIN IMMEDIATE"))
            yield
            await self.session.commit()
        except (IntegrityError, OperationalError) as error:
            await self.session.rollback()
            raise ConflictError("任务状态已变化或数据库繁忙，请重试。") from error
        except BaseException:
            await self.session.rollback()
            raise

    async def _run(self, run_id: UUID) -> TrainingRun:
        run = await self.session.get(TrainingRun, run_id, populate_existing=True)
        if run is None:
            raise NotFoundError("模拟训练任务不存在。")
        return run

    @staticmethod
    def read(run: TrainingRun) -> RunRead:
        # Never return the frozen system prompt or a worker's ownership token.
        public = {
            key: value
            for key, value in run.snapshot.items()
            if key
            in {
                "schema_version",
                "request",
                "agent_revision_id",
                "agent_config_sha256",
                "manifest_sha256",
                "content_sha256",
                "splits",
                "source_course_ids",
                "dataset_review_sequence",
                "code_sha256",
                "python_version",
            }
        }
        request = dict(public.get("request", {}))
        request.pop("idempotency_key", None)
        public["request"] = request
        return RunRead(
            id=run.id,
            agent_profile_id=run.agent_profile_id,
            agent_revision_id=run.agent_revision_id,
            dataset_revision_id=run.dataset_revision_id,
            retry_of=run.retry_of,
            status=run.status,
            completed_steps=run.completed_steps,
            total_steps=run.total_steps,
            last_code=run.last_code,
            snapshot_sha256=run.snapshot_sha256,
            source=public,
            result=run.result,
            started_at=run.started_at,
            finished_at=run.finished_at,
            created_at=run.created_at,
        )

    async def get(self, run_id: UUID) -> RunRead:
        return self.read(await self._run(run_id))

    async def list_runs(
        self, limit: int, offset: int, agent_id: UUID | None = None
    ) -> list[RunRead]:
        query = select(TrainingRun)
        if agent_id is not None:
            query = query.where(TrainingRun.agent_profile_id == agent_id)
        runs = await self.session.scalars(
            query.order_by(TrainingRun.created_at.desc(), TrainingRun.id)
            .limit(limit)
            .offset(offset)
        )
        return [self.read(run) for run in runs]

    async def events(self, run_id: UUID, after: int, limit: int) -> list[EventRead]:
        await self._run(run_id)
        events = await self.session.scalars(
            select(TrainingEvent)
            .where(
                TrainingEvent.run_id == run_id,
                TrainingEvent.sequence > after,
            )
            .order_by(TrainingEvent.sequence)
            .limit(limit)
        )
        return [EventRead.model_validate(item, from_attributes=True) for item in events]

    async def _snapshot(self, request: RunCreate, original: TrainingRun | None) -> RunSnapshot:
        from app.training.adapter_service import AdapterService

        await AdapterService(self.session, self.settings).predecessor(request)
        data_service = DatasetService(self.session, self.settings)
        revision = await data_service.require_eligible(
            request.dataset_id, request.dataset_revision_id, request.agent_profile_id
        )
        if revision.manifest.target != request.target:
            raise InvalidInputError("数据标签 schema 与训练目标不匹配。")
        if original is None:
            agent_revision = await self.session.scalar(
                select(AgentProfileRevision)
                .where(AgentProfileRevision.agent_profile_id == request.agent_profile_id)
                .order_by(AgentProfileRevision.revision_number.desc())
                .limit(1)
            )
        else:
            agent_revision = await self.session.get(
                AgentProfileRevision, original.agent_revision_id
            )
        if agent_revision is None:
            raise InvalidInputError("智能体配置版本不存在。")
        if (
            request.expected_agent_revision_id is not None
            and request.expected_agent_revision_id != agent_revision.id
        ):
            raise ConflictError("智能体版本已变化，请重新复核后提交。")
        config = agent_revision.read_config()
        if not set(revision.manifest.source_course_ids) <= set(config.allowed_course_ids):
            raise InvalidInputError("冻结智能体版本未允许该来源空间。")
        review = await data_service.repository.latest_review(revision.id)
        assert review is not None
        return RunSnapshot(
            request=request,
            agent_revision_id=agent_revision.id,
            agent_config_sha256=agent_revision.config_sha256,
            agent_configuration=config,
            manifest_sha256=revision.manifest_sha256,
            content_sha256=revision.report.content_sha256,
            splits=dict(revision.report.splits),
            source_course_ids=revision.manifest.source_course_ids,
            dataset_review_sequence=review.sequence,
            code_sha256=code_identity(),
            python_version=platform.python_version(),
        )

    async def create(
        self,
        request: RunCreate | None,
        *,
        retry_of: UUID | None = None,
        retry_key: str | None = None,
    ) -> RunRead:
        async with self.transaction():
            original = await self._run(retry_of) if retry_of else None
            if original is not None:
                if original.status not in {"failed", "cancelled", "interrupted"}:
                    raise ConflictError("只有失败、取消或中断的任务可以重试。")
                self._parse(original)
                request = RunCreate.model_validate(
                    {**original.snapshot["request"], "idempotency_key": retry_key}
                )
            assert request is not None
            fingerprint = digest(
                canonical(
                    {
                        "request": request.model_dump(mode="json"),
                        "retry_of": str(retry_of) if retry_of else None,
                    }
                )
            )
            existing = await self.session.scalar(
                select(TrainingRun).where(TrainingRun.idempotency_key == request.idempotency_key)
            )
            if existing is not None:
                if existing.request_sha256 != fingerprint:
                    raise ConflictError("同一幂等键不能用于不同任务参数。")
                return self.read(existing)
            snapshot = await self._snapshot(request, original)
            frozen = snapshot.model_dump(mode="json")
            run = TrainingRun(
                id=uuid4(),
                agent_profile_id=request.agent_profile_id,
                agent_revision_id=snapshot.agent_revision_id,
                dataset_revision_id=request.dataset_revision_id,
                retry_of=retry_of,
                idempotency_key=request.idempotency_key,
                request_sha256=fingerprint,
                snapshot=frozen,
                snapshot_sha256=digest(canonical(frozen)),
                total_steps=request.simulation_steps,
            )
            self.session.add(run)
            await self.session.flush()
            return self.read(run)

    def _parse(self, run: TrainingRun) -> RunSnapshot:
        if digest(canonical(run.snapshot)) != run.snapshot_sha256:
            raise InvalidInputError("任务配置快照完整性检查失败。")
        snapshot = RunSnapshot.model_validate(run.snapshot)
        if (
            snapshot.agent_configuration.sha256() != snapshot.agent_config_sha256
            or snapshot.agent_revision_id != run.agent_revision_id
            or snapshot.request.agent_profile_id != run.agent_profile_id
            or snapshot.request.dataset_revision_id != run.dataset_revision_id
            or snapshot.request.idempotency_key != run.idempotency_key
            or snapshot.request.simulation_steps != run.total_steps
        ):
            raise InvalidInputError("任务来源身份不一致。")
        return snapshot

    async def _preflight(self, run: TrainingRun) -> RunSnapshot:
        snapshot = self._parse(run)
        current = await self._snapshot(snapshot.request, run)
        if (
            current.agent_config_sha256 != snapshot.agent_config_sha256
            or current.manifest_sha256 != snapshot.manifest_sha256
            or current.content_sha256 != snapshot.content_sha256
            or current.splits != snapshot.splits
            or current.code_sha256 != snapshot.code_sha256
        ):
            raise InvalidInputError("任务依赖已变化，不能运行原冻结任务。")
        return snapshot

    async def cancel(self, run_id: UUID) -> RunRead:
        async with self.transaction():
            run = await self._run(run_id)
            if run.status == "queued":
                run.status = "cancelled"
                run.finished_at = self.clock()
                run.last_code = "USER_CANCELLED"
            elif run.status == "running":
                run.status = "cancelling"
                run.last_code = "USER_CANCEL_REQUESTED"
            await self.session.flush()
            return self.read(run)

    async def _lease(self) -> TrainingWorkerLease:
        lease = await self.session.get(TrainingWorkerLease, 1, populate_existing=True)
        if lease is None:
            lease = TrainingWorkerLease(id=1, expires_at=0)
            self.session.add(lease)
            await self.session.flush()
        return lease

    async def claim(self) -> tuple[UUID, str, RunSnapshot] | None:
        async with self.transaction():
            lease = await self._lease()
            if lease.owner_token and lease.expires_at > self.clock():
                return None
            # Only an absent/expired lease authorizes recovery; never interrupt a live worker.
            orphaned = list(
                await self.session.scalars(
                    select(TrainingRun).where(TrainingRun.status.in_(["running", "cancelling"]))
                )
            )
            for orphan in orphaned:
                orphan.status = "cancelled" if orphan.status == "cancelling" else "interrupted"
                orphan.last_code = "WORKER_LOST"
                orphan.finished_at = self.clock()
            lease.owner_token = None
            lease.expires_at = 0
            await self.session.flush()
            run = await self.session.scalar(
                select(TrainingRun)
                .where(TrainingRun.status == "queued")
                .order_by(TrainingRun.created_at, TrainingRun.id)
                .limit(1)
            )
            if run is None:
                return None
            try:
                snapshot = await self._preflight(run)
            except (InvalidInputError, ValueError):
                run.status = "cancelled"
                run.last_code = "PRECHECK_FAILED"
                run.finished_at = self.clock()
                return None
            token = uuid4().hex
            lease.owner_token = token
            lease.expires_at = self.clock() + self.settings.training_lease_seconds
            run.status = "running"
            run.owner_token = token
            run.started_at = self.clock()
            run.last_code = "SIMULATION_STARTED"
            await self.session.flush()
            return run.id, token, snapshot

    async def renew(self, token: str) -> bool:
        async with self.transaction():
            lease = await self._lease()
            if lease.owner_token != token or lease.expires_at <= self.clock():
                return False
            lease.expires_at = self.clock() + self.settings.training_lease_seconds
            return True

    async def _owned(
        self, run_id: UUID, token: str
    ) -> tuple[TrainingRun, TrainingWorkerLease] | None:
        run = await self._run(run_id)
        lease = await self._lease()
        if (
            run.status in TERMINAL
            or run.owner_token != token
            or lease.owner_token != token
            or lease.expires_at <= self.clock()
        ):
            return None
        return run, lease

    async def progress(self, run_id: UUID, token: str, step: int) -> bool:
        async with self.transaction():
            owned = await self._owned(run_id, token)
            if owned is None:
                return False
            run, lease = owned
            if run.status == "cancelling":
                return False
            if (
                step < run.completed_steps
                or step > run.completed_steps + 1
                or step > run.total_steps
            ):
                raise InvalidInputError("训练进度事件无效。")
            if step != run.completed_steps:
                run.completed_steps = step
                run.last_code = "SIMULATED_STEP"
            lease.expires_at = self.clock() + self.settings.training_lease_seconds
            return True

    async def finish(
        self,
        run_id: UUID,
        token: str,
        result: dict[str, Any] | None,
        *,
        failed: bool = False,
        interrupted: bool = False,
    ) -> bool:
        async with self.transaction():
            owned = await self._owned(run_id, token)
            if owned is None:
                return False
            run, lease = owned
            if run.status == "cancelling":
                run.status = "cancelled"
                # Preserve the dependency/user cancellation reason in the last event.
            elif interrupted:
                run.status = "interrupted"
                run.last_code = "WORKER_SHUTDOWN"
            elif failed or result is None:
                run.status = "failed"
                run.last_code = "TRAINER_FAILED"
            else:
                try:
                    await self._preflight(run)
                except (InvalidInputError, ValueError):
                    run.status = "failed"
                    run.last_code = "FINAL_CHECK_FAILED"
                else:
                    if (
                        run.completed_steps != run.total_steps
                        or result.get("deployable") is not False
                        or result.get("artifact_kind") != "simulated"
                    ):
                        raise InvalidInputError("模拟训练完成结果不合法。")
                    run.status = "succeeded"
                    run.last_code = "SIMULATION_SUCCEEDED"
                    run.result = result
            run.finished_at = self.clock()
            if run.status == "succeeded":
                from app.training.adapter_service import AdapterService

                await self.session.flush()
                await AdapterService(self.session, self.settings).register(run)
            lease.owner_token = None
            lease.expires_at = 0
            return True
