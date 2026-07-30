from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentStatus


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        course_id: UUID,
        original_name: str,
        stored_name: str,
        file_type: str,
        file_size: int,
        sha256: str,
        status: DocumentStatus = DocumentStatus.PENDING,
    ) -> Document:
        document = Document(
            course_id=course_id,
            original_name=original_name,
            stored_name=stored_name,
            file_type=file_type,
            file_size=file_size,
            sha256=sha256,
            status=status,
        )
        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def get(self, document_id: UUID) -> Document | None:
        return await self.session.get(Document, document_id)

    async def get_by_course_and_sha256(
        self,
        *,
        course_id: UUID,
        sha256: str,
    ) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.course_id == course_id,
                Document.sha256 == sha256,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_course(self, course_id: UUID) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.course_id == course_id)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars())

    async def delete(self, document: Document) -> None:
        await self.session.delete(document)
        await self.session.flush()
