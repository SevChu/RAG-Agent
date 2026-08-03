from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Document, DocumentProcessingStage, DocumentStatus
from app.repositories import CourseRepository, DocumentRepository


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.course_repository = CourseRepository(session)
        self.repository = DocumentRepository(session)

    async def register(
        self,
        *,
        document_id: UUID,
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
            raise InvalidInputError("File size cannot be negative.")
        normalized_hash = sha256.strip().lower()
        if len(normalized_hash) != 64:
            raise InvalidInputError("SHA-256 must contain 64 hexadecimal characters.")
        try:
            int(normalized_hash, 16)
        except ValueError as error:
            raise InvalidInputError(
                "SHA-256 must contain 64 hexadecimal characters."
            ) from error
        if await self.repository.get_by_course_and_sha256(
            course_id=course_id,
            sha256=normalized_hash,
        ):
            raise ConflictError("This file already exists in the course.")

        try:
            document = await self.repository.create(
                document_id=document_id,
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

    async def get(self, document_id: UUID) -> Document:
        document = await self.repository.get(document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    async def list_for_course(self, course_id: UUID) -> list[Document]:
        if await self.course_repository.get(course_id) is None:
            raise NotFoundError("Course not found.")
        return await self.repository.list_for_course(course_id)

    async def get_many_for_course(
        self,
        *,
        course_id: UUID,
        document_ids: list[UUID],
    ) -> list[Document]:
        if await self.course_repository.get(course_id) is None:
            raise NotFoundError("Course not found.")
        documents = await self.repository.list_by_ids(document_ids)
        documents_by_id = {
            document.id: document
            for document in documents
            if document.course_id == course_id
        }
        if len(documents_by_id) != len(document_ids):
            raise NotFoundError("One or more documents were not found in the course.")
        return [documents_by_id[document_id] for document_id in document_ids]

    async def delete(self, document_id: UUID) -> Document:
        document = await self.get(document_id)
        await self.repository.delete(document)
        await self.session.commit()
        return document

    async def delete_many(self, documents: list[Document]) -> None:
        try:
            for document in documents:
                await self.repository.delete(document)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def request_reindex(self, document_id: UUID) -> Document:
        document = await self.get(document_id)
        if document.status in {DocumentStatus.PENDING, DocumentStatus.PROCESSING}:
            raise ConflictError("This document is already waiting or being processed.")
        await self.repository.update_status(
            document,
            status=DocumentStatus.PENDING,
            error_message=None,
        )
        document.progress_percent = 0
        document.processing_stage = DocumentProcessingStage.WAITING
        document.progress_detail = "等待后台处理"
        await self.session.commit()
        return document
