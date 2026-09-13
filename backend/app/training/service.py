from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import (
    AgentProfile,
    AgentProfileRevision,
    Course,
    TrainingDataset,
    TrainingDatasetReview,
    TrainingDatasetRevision,
)
from app.training.repository import DatasetRepository
from app.training.schemas import (
    DatasetCreate,
    DatasetManifest,
    DatasetRead,
    EligibilityRead,
    ReviewRead,
    ReviewRequest,
    RevisionRead,
    ValidationReport,
)
from app.training.storage import DatasetStorage
from app.training.validation import canonical, digest, has_sensitive_text, validate_jsonl


class DatasetService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        if settings.agentic_edition != "research":
            raise HTTPException(status_code=403, detail="训练数据管理仅在科研模式可用。")
        self.session = session
        self.repository = DatasetRepository(session)
        self.storage = DatasetStorage(settings.training_data_dir)

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[None]:
        try:
            yield
            await self.session.commit()
        except (IntegrityError, StaleDataError) as error:
            await self.session.rollback()
            raise ConflictError("名称重复或数据审核版本已变化，请刷新后重试。") from error
        except OperationalError as error:
            await self.session.rollback()
            raise ConflictError("数据库暂不可写，请稍后重试。") from error
        except Exception:
            await self.session.rollback()
            raise

    async def _dataset(self, dataset_id: UUID) -> TrainingDataset:
        dataset = await self.repository.dataset(dataset_id)
        if dataset is None:
            raise NotFoundError("训练数据集不存在。")
        return dataset

    async def _revision(self, dataset_id: UUID, revision_id: UUID) -> TrainingDatasetRevision:
        revision = await self.repository.revision(dataset_id, revision_id)
        if revision is None:
            raise NotFoundError("该数据集的版本不存在。")
        return revision

    async def _claim(self, dataset_id: UUID, expected: int) -> TrainingDataset:
        dataset = await self._dataset(dataset_id)
        if dataset.row_version != expected:
            raise ConflictError("数据集已被修改，请刷新后重试。")
        dataset.row_version += 1
        await self.session.flush()
        return dataset

    async def _check_spaces(self, manifest: DatasetManifest) -> None:
        if manifest.source_course_ids:
            existing = set(
                await self.session.scalars(
                    select(Course.id).where(Course.id.in_(manifest.source_course_ids))
                )
            )
            if existing != set(manifest.source_course_ids):
                raise InvalidInputError("数据来源资料空间不存在或已删除。")

    async def create(self, payload: DatasetCreate) -> DatasetRead:
        if has_sensitive_text(payload.name):
            raise InvalidInputError("数据集名称包含疑似敏感信息。")
        async with self._write():
            dataset = TrainingDataset(name=payload.name)
            self.session.add(dataset)
            await self.session.flush()
            result = DatasetRead.model_validate(dataset, from_attributes=True)
        return result

    async def get(self, dataset_id: UUID) -> DatasetRead:
        return DatasetRead.model_validate(await self._dataset(dataset_id), from_attributes=True)

    async def list_datasets(self, limit: int, offset: int) -> list[DatasetRead]:
        return [
            DatasetRead.model_validate(item, from_attributes=True)
            for item in await self.repository.datasets(limit, offset)
        ]

    async def read_revision(self, revision: TrainingDatasetRevision) -> RevisionRead:
        review = await self.repository.latest_review(revision.id)
        return RevisionRead.model_validate(
            {
                "id": revision.id,
                "dataset_id": revision.dataset_id,
                "revision_number": revision.revision_number,
                "manifest": revision.manifest,
                "manifest_sha256": revision.manifest_sha256,
                "report": revision.report,
                "status": review.status if review else "draft",
                "created_at": revision.created_at,
            }
        )

    async def get_revision(self, dataset_id: UUID, revision_id: UUID) -> RevisionRead:
        return await self.read_revision(await self._revision(dataset_id, revision_id))

    async def list_revisions(self, dataset_id: UUID, limit: int, offset: int) -> list[RevisionRead]:
        await self._dataset(dataset_id)
        return [
            await self.read_revision(item)
            for item in await self.repository.revisions(dataset_id, limit, offset)
        ]

    async def import_revision(
        self, dataset_id: UUID, expected: int, manifest: DatasetManifest, data: bytes
    ) -> RevisionRead:
        report = await run_in_threadpool(validate_jsonl, data, manifest)
        if not report.valid:
            issue = report.issues[0]
            raise InvalidInputError(f"数据校验失败：{issue.code}；行号 {issue.line or 0}。")
        # Metadata is displayed in the catalog; unlike private samples it cannot be quarantined.
        if has_sensitive_text(canonical(manifest.model_dump(mode="json")).decode()):
            raise InvalidInputError("来源说明含疑似敏感信息，请脱敏后再登记。")
        async with self._write():
            await self._claim(dataset_id, expected)
            await self._check_spaces(manifest)
            revision = TrainingDatasetRevision(
                id=uuid4(),
                dataset_id=dataset_id,
                revision_number=await self.repository.next_revision(dataset_id),
                manifest=manifest.model_dump(mode="json"),
                manifest_sha256=digest(canonical(manifest.model_dump(mode="json"))),
                report=report.model_dump(mode="json"),
            )
            self.session.add(revision)
            await self.session.flush()
            self.session.add(
                TrainingDatasetReview(
                    revision_id=revision.id,
                    sequence=1,
                    status="draft",
                    reviewer="system",
                    note="数据导入完成，尚未审核。",
                )
            )
            await self.session.flush()
            await run_in_threadpool(self.storage.write, revision.id, data)
            result = await self.read_revision(revision)
        # A crash after file creation but before commit leaves an unreferenced UUID file.
        # It is never served or selected; later reviewed cleanup can remove it.
        return result

    async def _verify(self, revision: TrainingDatasetRevision) -> ValidationReport:
        try:
            manifest = DatasetManifest.model_validate(revision.manifest)
            frozen = ValidationReport.model_validate(revision.report)
        except ValidationError as error:
            raise InvalidInputError("数据版本元信息已损坏。") from error
        if digest(canonical(manifest.model_dump(mode="json"))) != revision.manifest_sha256:
            raise InvalidInputError("数据来源快照哈希不一致。")
        await self._check_spaces(manifest)
        data = await run_in_threadpool(self.storage.read, revision.id)
        if digest(data) != frozen.content_sha256:
            raise InvalidInputError("训练文件哈希不一致，请新建版本。")
        report = await run_in_threadpool(validate_jsonl, data, manifest)
        if report != frozen:
            raise InvalidInputError("数据校验报告与冻结记录不一致。")
        return report

    async def review(
        self, dataset_id: UUID, revision_id: UUID, payload: ReviewRequest
    ) -> ReviewRead:
        if has_sensitive_text(payload.reviewer + " " + payload.note):
            raise InvalidInputError("审核信息包含疑似敏感内容，请先脱敏。")
        async with self._write():
            await self._claim(dataset_id, payload.expected_row_version)
            revision = await self._revision(dataset_id, revision_id)
            latest = await self.repository.latest_review(revision.id)
            current = latest.status if latest else "draft"
            transitions = {
                "draft": {"pending_review"},
                "pending_review": {"approved", "rejected"},
                "approved": {"revoked"},
                "rejected": {"pending_review"},
                "revoked": {"pending_review"},
            }
            if payload.status not in transitions[current]:
                raise ConflictError("该审核状态转换不允许。")
            if payload.status == "approved":
                report = await self._verify(revision)
                if not report.approvable:
                    raise InvalidInputError("数据未通过许可、隐私或去重检查，不能批准。")
            event = TrainingDatasetReview(
                revision_id=revision.id,
                sequence=(latest.sequence if latest else 0) + 1,
                status=payload.status,
                reviewer=payload.reviewer,
                note=payload.note,
            )
            self.session.add(event)
            await self.session.flush()
            result = ReviewRead.model_validate(event, from_attributes=True)
        return result

    async def reviews(
        self, dataset_id: UUID, revision_id: UUID, limit: int, offset: int
    ) -> list[ReviewRead]:
        await self._revision(dataset_id, revision_id)
        return [
            ReviewRead.model_validate(event, from_attributes=True)
            for event in await self.repository.reviews(revision_id, limit, offset)
        ]

    async def eligibility(
        self, dataset_id: UUID, revision_id: UUID, agent_profile_id: UUID
    ) -> EligibilityRead:
        revision = await self._revision(dataset_id, revision_id)
        reasons: list[str] = []
        latest = await self.repository.latest_review(revision.id)
        if latest is None or latest.status != "approved":
            reasons.append("DATASET_NOT_APPROVED")
        profile = await self.session.get(AgentProfile, agent_profile_id, populate_existing=True)
        agent_revision = await self.session.scalar(
            select(AgentProfileRevision)
            .where(
                AgentProfileRevision.agent_profile_id == agent_profile_id,
            )
            .order_by(AgentProfileRevision.revision_number.desc())
            .limit(1)
        )
        if profile is None or profile.deleted_at is not None or not profile.enabled:
            reasons.append("AGENT_UNAVAILABLE")
        elif agent_revision is None:
            reasons.append("AGENT_REVISION_MISSING")
        else:
            try:
                config = agent_revision.read_config()
                manifest = DatasetManifest.model_validate(revision.manifest)
                if not set(manifest.source_course_ids) <= set(config.allowed_course_ids):
                    reasons.append("SOURCE_SPACE_NOT_ALLOWED")
            except ValueError:
                reasons.append("CONFIGURATION_INVALID")
        report = None
        try:
            report = await self._verify(revision)
            if not report.approvable:
                reasons.append("DATASET_CHECKS_FAILED")
        except (InvalidInputError, ValueError):
            reasons.append("DATASET_INTEGRITY_OR_SOURCE_INVALID")
        return EligibilityRead(
            revision_id=revision.id, eligible=not reasons, reasons=tuple(reasons), report=report
        )

    async def require_eligible(
        self, dataset_id: UUID, revision_id: UUID, agent_profile_id: UUID
    ) -> RevisionRead:
        """Day 2 must call at submission AND before execution, never trust a UI flag."""
        result = await self.eligibility(dataset_id, revision_id, agent_profile_id)
        if not result.eligible:
            raise InvalidInputError("训练数据不可用：" + ", ".join(result.reasons))
        return await self.get_revision(dataset_id, revision_id)
