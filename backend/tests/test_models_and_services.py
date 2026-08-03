from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models import Course, Document, DocumentProcessingStage, DocumentStatus
from app.repositories import CourseRepository
from app.services import CourseService, DocumentService


async def test_course_service_normalizes_and_rejects_duplicate_names(
    db_session: AsyncSession,
) -> None:
    service = CourseService(db_session)

    course = await service.create(
        name="  数据结构  ",
        description="  核心课程  ",
    )

    assert course.name == "数据结构"
    assert course.description == "核心课程"

    with pytest.raises(ConflictError, match="already exists"):
        await service.create(name="数据结构")

    assert len(await service.list()) == 1


async def test_document_hash_is_unique_per_course_only(
    db_session: AsyncSession,
) -> None:
    course_service = CourseService(db_session)
    document_service = DocumentService(db_session)
    first_course = await course_service.create(name="操作系统")
    second_course = await course_service.create(name="计算机网络")
    sha256 = "a" * 64

    first_document = await document_service.register(
        document_id=uuid4(),
        course_id=first_course.id,
        original_name="lecture.pdf",
        stored_name=f"{uuid4()}.pdf",
        file_type="PDF",
        file_size=1024,
        sha256=sha256,
    )

    assert first_document.status is DocumentStatus.PENDING
    assert first_document.progress_percent == 0
    assert first_document.processing_stage is DocumentProcessingStage.WAITING
    assert first_document.progress_detail == "等待后台处理"
    assert first_document.file_type == "pdf"

    with pytest.raises(ConflictError, match="already exists"):
        await document_service.register(
            document_id=uuid4(),
            course_id=first_course.id,
            original_name="renamed.pdf",
            stored_name=f"{uuid4()}.pdf",
            file_type="pdf",
            file_size=1024,
            sha256=sha256,
        )

    second_document = await document_service.register(
        document_id=uuid4(),
        course_id=second_course.id,
        original_name="lecture.pdf",
        stored_name=f"{uuid4()}.pdf",
        file_type="pdf",
        file_size=1024,
        sha256=sha256,
    )

    assert second_document.course_id == second_course.id


async def test_deleting_course_cascades_to_document_records(
    db_session: AsyncSession,
) -> None:
    course_service = CourseService(db_session)
    document_service = DocumentService(db_session)
    course = await course_service.create(name="编译原理")
    await document_service.register(
        document_id=uuid4(),
        course_id=course.id,
        original_name="chapter-1.pdf",
        stored_name=f"{uuid4()}.pdf",
        file_type="pdf",
        file_size=2048,
        sha256="b" * 64,
    )

    repository = CourseRepository(db_session)
    persisted_course = await repository.get(course.id)
    assert persisted_course is not None
    await repository.delete(persisted_course)
    await db_session.commit()

    course_count = await db_session.scalar(select(func.count()).select_from(Course))
    document_count = await db_session.scalar(select(func.count()).select_from(Document))
    assert course_count == 0
    assert document_count == 0
