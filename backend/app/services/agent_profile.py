from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.agents.configuration import AgentConfiguration
from app.agents.validation import (
    load_evaluation_catalog,
    profile_usages,
    validate_configuration_dependencies,
)
from app.core.config import Settings
from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import AgentProfile, AgentProfileRevision
from app.repositories.agent_profile import AgentProfileRepository, ProfileRecord
from app.schemas.agent_profile import (
    AgentEvaluationOption,
    AgentProfileCopy,
    AgentProfileCreate,
    AgentProfileOptions,
    AgentProfileRead,
    AgentProfileRestore,
    AgentProfileUpdate,
    AgentProviderOption,
    AgentRevisionRead,
)


class AgentProfileService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = AgentProfileRepository(session)

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[None]:
        try:
            yield
            await self.session.commit()
        except (IntegrityError, StaleDataError) as error:
            await self.session.rollback()
            raise ConflictError("智能体名称重复或配置已被其他请求修改，请刷新后重试。") from error
        except OperationalError as error:
            await self.session.rollback()
            code = getattr(error.orig, "sqlite_errorcode", 0)
            if isinstance(code, int) and code & 255 in (5, 6):
                raise ConflictError("数据库正在处理其他修改，请刷新后重试。") from error
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def _record(self, profile_id: UUID) -> ProfileRecord:
        record = await self.repository.get(profile_id)
        if record is None:
            raise NotFoundError("智能体不存在或尚无可用配置版本。")
        return record

    async def _revision(self, profile_id: UUID, revision_id: UUID) -> AgentProfileRevision:
        revision = await self.repository.revision(profile_id, revision_id)
        if revision is None:
            raise NotFoundError("该智能体的配置版本不存在。")
        return revision

    @staticmethod
    def _configuration(revision: AgentProfileRevision) -> AgentConfiguration:
        try:
            return revision.read_config()
        except ValueError as error:
            raise ConflictError("保存的配置快照校验失败，请检查本地数据。") from error

    @classmethod
    def _revision_read(cls, revision: AgentProfileRevision) -> AgentRevisionRead:
        return AgentRevisionRead(
            id=revision.id,
            agent_profile_id=revision.agent_profile_id,
            revision_number=revision.revision_number,
            config=cls._configuration(revision),
            config_sha256=revision.config_sha256,
            change_summary=revision.change_summary,
            created_at=revision.created_at,
        )

    @classmethod
    def _read(cls, profile: AgentProfile, revision: AgentProfileRevision) -> AgentProfileRead:
        return AgentProfileRead(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            enabled=profile.enabled,
            deleted_at=profile.deleted_at,
            row_version=profile.row_version,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            current_revision=cls._revision_read(revision),
        )

    async def validate_configuration(self, config: AgentConfiguration) -> None:
        if self.settings.agentic_edition == "product":
            config = config.model_copy(update={"evaluation_profiles": ()})
        validate_configuration_dependencies(
            config,
            self.settings,
            existing_course_ids=await self.repository.existing_courses(config.allowed_course_ids),
            catalog=load_evaluation_catalog() if config.evaluation_profiles else None,
        )

    def options(self) -> AgentProfileOptions:
        catalog = load_evaluation_catalog() if self.settings.agentic_edition == "research" else None
        return AgentProfileOptions(
            edition=self.settings.agentic_edition,
            providers=[
                AgentProviderOption(
                    id=p.id, name=p.name, models=list(p.models), configured=p.configured
                )
                for p in self.settings.llm_providers
            ],
            evaluation_profiles=[
                AgentEvaluationOption(
                    profile_id=p.profile_id,
                    registry_version=catalog.registry.release_version,
                    registry_sha256=catalog.sha256,
                    allowed_usages=profile_usages(p),
                )
                for p in (catalog.registry.profiles if catalog is not None else ())
                if catalog is not None and profile_usages(p)
            ],
            external_search_enabled=self.settings.external_search_enabled,
        )

    async def create(self, payload: AgentProfileCreate) -> AgentProfileRead:
        if self.settings.agentic_edition == "product" and payload.config.evaluation_profiles:
            raise InvalidInputError("产品模式不能新增研究评测引用，请使用研发/科研模式。")
        async with self._write():
            await self.validate_configuration(payload.config)
            profile = await self.repository.create(
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
            )
            revision = await self.repository.append(
                profile.id,
                number=1,
                config=payload.config,
                summary=payload.change_summary,
            )
            await self.session.refresh(profile)
            result = self._read(profile, revision)
        return result

    async def get(self, profile_id: UUID) -> AgentProfileRead:
        return self._read(*(await self._record(profile_id)))

    async def list_profiles(
        self, *, enabled: bool | None = None, limit: int = 50, offset: int = 0
    ) -> list[AgentProfileRead]:
        return [
            self._read(*record)
            for record in await self.repository.list_profiles(
                enabled=enabled, limit=limit, offset=offset
            )
        ]

    async def revisions(
        self, profile_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[AgentRevisionRead]:
        await self._record(profile_id)
        return [
            self._revision_read(revision)
            for revision in await self.repository.revisions(profile_id, limit=limit, offset=offset)
        ]

    async def revision(self, profile_id: UUID, revision_id: UUID) -> AgentRevisionRead:
        return self._revision_read(await self._revision(profile_id, revision_id))

    @staticmethod
    def _check_active(profile: AgentProfile) -> None:
        if profile.deleted_at is not None:
            raise ConflictError("智能体已删除，不能修改、复制或恢复；历史仍可查看。")

    async def delete(self, profile_id: UUID, expected_row_version: int) -> None:
        async with self._write():
            profile, _ = await self._record(profile_id)
            if profile.deleted_at is not None:
                return
            self._check_version(profile, expected_row_version)
            profile.deleted_at = datetime.now(UTC)
            profile.enabled = False
            profile.row_version += 1
            await self.session.flush()

    @staticmethod
    def _check_version(profile: AgentProfile, expected: int) -> None:
        if profile.row_version != expected:
            raise ConflictError("智能体已被修改，请刷新配置后重试。")

    async def update(self, profile_id: UUID, payload: AgentProfileUpdate) -> AgentProfileRead:
        async with self._write():
            profile, revision = await self._record(profile_id)
            self._check_active(profile)
            self._check_version(profile, payload.expected_row_version)
            if (
                self.settings.agentic_edition == "product"
                and payload.config is not None
                and payload.config.evaluation_profiles
                and payload.config.evaluation_profiles
                != self._configuration(revision).evaluation_profiles
            ):
                raise InvalidInputError("产品模式不能新增或修改研究引用；已有引用可保留或清空。")
            if payload.config is not None or payload.enabled is True:
                await self.validate_configuration(
                    payload.config if payload.config is not None else self._configuration(revision)
                )
            if payload.name is not None:
                profile.name = payload.name
            if "description" in payload.model_fields_set:
                profile.description = payload.description
            if payload.enabled is not None:
                profile.enabled = payload.enabled
            # Even a config-only update must claim the identity row before appending.
            profile.row_version += 1
            await self.session.flush()
            if payload.config is not None:
                revision = await self.repository.append(
                    profile.id,
                    number=revision.revision_number + 1,
                    config=payload.config,
                    summary=payload.change_summary,
                )
            await self.session.refresh(profile)
            result = self._read(profile, revision)
        return result

    async def copy(self, profile_id: UUID, payload: AgentProfileCopy) -> AgentProfileRead:
        profile, source = await self._record(profile_id)
        self._check_active(profile)
        if payload.revision_id is not None:
            source = await self._revision(profile_id, payload.revision_id)
        config = self._configuration(source)
        if self.settings.agentic_edition == "product":
            config = config.model_copy(update={"evaluation_profiles": ()})
        return await self.create(
            AgentProfileCreate(
                name=payload.name,
                description=payload.description,
                enabled=payload.enabled,
                config=config,
                change_summary=f"复制自 {profile_id} / r{source.revision_number}",
            )
        )

    async def restore(self, profile_id: UUID, payload: AgentProfileRestore) -> AgentProfileRead:
        async with self._write():
            profile, current = await self._record(profile_id)
            self._check_active(profile)
            self._check_version(profile, payload.expected_row_version)
            source = await self._revision(profile_id, payload.revision_id)
            config = self._configuration(source)
            await self.validate_configuration(config)
            profile.row_version += 1
            await self.session.flush()
            revision = await self.repository.append(
                profile.id,
                number=current.revision_number + 1,
                config=config,
                summary=payload.change_summary,
            )
            await self.session.refresh(profile)
            result = self._read(profile, revision)
        return result
