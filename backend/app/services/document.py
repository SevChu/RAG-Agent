from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Document
from app.repositories import CourseRepository, DocumentRepository


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.course_repository = CourseRepository(session)
        self.repository = DocumentRepository(session)

    async def register(
        self,
        *,
        course_id: UUID,
        original_name: str,
        stored_name: str,
        file_type: str,
        file_size: int,
        sha256: str,
    ) -> Document:
        if await self.course_repository.get(course_id) is None:
            raise NotFoundError("Course not found.")
        if file_size < 0:
            raise ValueError("File size cannot be negative.")
        normalized_hash = sha256.strip().lower()
        if len(normalized_hash) != 64:
            raise ValueError("SHA-256 must contain 64 hexadecimal characters.")
        try:
            int(normalized_hash, 16)
        except ValueError as error:
            raise ValueError("SHA-256 must contain 64 hexadecimal characters.") from error
        if await self.repository.get_by_course_and_sha256(
            course_id=course_id,
            sha256=normalized_hash,
        ):
            raise ConflictError("This file already exists in the course.")

        try:
            document = await self.repository.create(
                course_id=course_id,
                original_name=original_name,
                stored_name=stored_name,
                file_type=file_type.lower(),
                file_size=file_size,
                sha256=normalized_hash,
            )
            await self.session.commit()
            return document
        except IntegrityError as error:
            await self.session.rollback()
            raise ConflictError("This file already exists in the course.") from error
