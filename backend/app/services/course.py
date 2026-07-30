from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Course
from app.repositories import CourseRepository


class CourseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CourseRepository(session)

    async def create(self, *, name: str, description: str | None = None) -> Course:
        normalized_name = name.strip()
        normalized_description = (description.strip() or None) if description else None
        if not normalized_name:
            raise InvalidInputError("Course name cannot be empty.")
        if len(normalized_name) > 100:
            raise InvalidInputError("Course name cannot exceed 100 characters.")
        if await self.repository.get_by_name(normalized_name):
            raise ConflictError("A course with this name already exists.")

        try:
            course = await self.repository.create(
                name=normalized_name,
                description=normalized_description,
            )
            await self.session.commit()
            return course
        except IntegrityError as error:
            await self.session.rollback()
            raise ConflictError("A course with this name already exists.") from error

    async def get(self, course_id: UUID) -> Course:
        course = await self.repository.get(course_id)
        if course is None:
            raise NotFoundError("Course not found.")
        return course

    async def list(self) -> list[Course]:
        return await self.repository.list()

    async def delete(self, course_id: UUID) -> Course:
        course = await self.get(course_id)
        await self.repository.delete(course)
        await self.session.commit()
        return course
