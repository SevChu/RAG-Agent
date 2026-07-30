from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course


class CourseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, name: str, description: str | None) -> Course:
        course = Course(name=name, description=description)
        self.session.add(course)
        await self.session.flush()
        await self.session.refresh(course)
        return course

    async def get(self, course_id: UUID) -> Course | None:
        return await self.session.get(Course, course_id)

    async def get_by_name(self, name: str) -> Course | None:
        result = await self.session.execute(select(Course).where(Course.name == name))
        return result.scalar_one_or_none()

    async def list(self) -> list[Course]:
        result = await self.session.execute(select(Course).order_by(Course.created_at.desc()))
        return list(result.scalars())

    async def delete(self, course: Course) -> None:
        await self.session.delete(course)
        await self.session.flush()
