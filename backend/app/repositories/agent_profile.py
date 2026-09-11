from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.configuration import AgentConfiguration
from app.models import AgentProfile, AgentProfileRevision, Course

ProfileRecord = tuple[AgentProfile, AgentProfileRevision]


class AgentProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _current_query() -> Select[ProfileRecord]:
        latest = (
            select(
                AgentProfileRevision.agent_profile_id,
                func.max(AgentProfileRevision.revision_number).label("number"),
            )
            .group_by(AgentProfileRevision.agent_profile_id)
            .subquery()
        )
        return (
            select(AgentProfile, AgentProfileRevision)
            .join(latest, latest.c.agent_profile_id == AgentProfile.id)
            .join(
                AgentProfileRevision,
                (AgentProfileRevision.agent_profile_id == AgentProfile.id)
                & (AgentProfileRevision.revision_number == latest.c.number),
            )
            .execution_options(populate_existing=True)
        )

    async def get(self, profile_id: UUID) -> ProfileRecord | None:
        row = (
            await self.session.execute(self._current_query().where(AgentProfile.id == profile_id))
        ).first()
        return (row[0], row[1]) if row is not None else None

    async def bound_revision(
        self,
        profile_id: UUID,
        revision_id: UUID | None,
    ) -> ProfileRecord | None:
        row = (
            await self.session.execute(
                select(AgentProfile, AgentProfileRevision)
                .join(
                    AgentProfileRevision,
                    AgentProfileRevision.agent_profile_id == AgentProfile.id,
                )
                .where(AgentProfile.id == profile_id, AgentProfileRevision.id == revision_id)
                .execution_options(populate_existing=True)
            )
        ).first()
        return (row[0], row[1]) if row is not None else None

    async def list_profiles(
        self, *, enabled: bool | None, limit: int, offset: int
    ) -> list[ProfileRecord]:
        query = self._current_query().where(AgentProfile.deleted_at.is_(None))
        if enabled is not None:
            query = query.where(AgentProfile.enabled == enabled)
        rows = await self.session.execute(
            query.order_by(AgentProfile.created_at.desc(), AgentProfile.id)
            .limit(limit)
            .offset(offset)
        )
        return [(row[0], row[1]) for row in rows]

    async def revision(self, profile_id: UUID, revision_id: UUID) -> AgentProfileRevision | None:
        result = await self.session.execute(
            select(AgentProfileRevision).where(
                AgentProfileRevision.id == revision_id,
                AgentProfileRevision.agent_profile_id == profile_id,
            )
        )
        return result.scalar_one_or_none()

    async def revisions(
        self, profile_id: UUID, *, limit: int, offset: int
    ) -> list[AgentProfileRevision]:
        return list(
            await self.session.scalars(
                select(AgentProfileRevision)
                .where(AgentProfileRevision.agent_profile_id == profile_id)
                .order_by(AgentProfileRevision.revision_number.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    async def existing_courses(self, ids: tuple[UUID, ...]) -> set[UUID]:
        if not ids:
            return set()
        return set(await self.session.scalars(select(Course.id).where(Course.id.in_(ids))))

    async def create(self, *, name: str, description: str | None, enabled: bool) -> AgentProfile:
        profile = AgentProfile(name=name, description=description, enabled=enabled)
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def append(
        self, profile_id: UUID, *, number: int, config: AgentConfiguration, summary: str
    ) -> AgentProfileRevision:
        revision = AgentProfileRevision(
            agent_profile_id=profile_id,
            revision_number=number,
            config=config.model_dump(mode="json"),
            change_summary=summary,
        )
        self.session.add(revision)
        await self.session.flush()
        return revision
