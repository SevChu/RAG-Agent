from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.indexing.runtime import (
    DocumentIndexingManager,
    DocumentIndexingPipeline,
    IndexingDocument,
    IndexingProgressCallback,
    friendly_indexing_error,
)
from app.ingestion.errors import EmptyDocumentError, InvalidDocumentFormatError
from app.models import Course, Document, DocumentProcessingStage, DocumentStatus


class FakePipeline:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.indexed: list[UUID] = []
        self.cleaned: list[UUID] = []

    def index(
        self,
        document: IndexingDocument,
        progress_callback: IndexingProgressCallback | None = None,
    ) -> int:
        self.indexed.append(document.id)
        if progress_callback is not None:
            progress_callback(DocumentProcessingStage.PARSING, 35, "正在解析测试资料")
        if self.error is not None:
            raise self.error
        if progress_callback is not None:
            progress_callback(DocumentProcessingStage.STORING, 99, "正在确认索引结果")
        return 3

    def delete_document(self, *, course_id: UUID, document_id: UUID) -> None:
        self.cleaned.append(document_id)

    def delete_course(self, *, course_id: UUID) -> None:
        return None

    def close(self) -> None:
        return None


async def _runtime(
    tmp_path: Path,
    pipeline: FakePipeline,
) -> tuple[
    DocumentIndexingManager,
    async_sessionmaker[AsyncSession],
    AsyncEngine,
    UUID,
]:
    database_path = (tmp_path / "runtime.db").as_posix()
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    course_id = uuid4()
    document_id = uuid4()
    async with session_factory() as session:
        session.add(Course(id=course_id, name="后台索引测试"))
        session.add(
            Document(
                id=document_id,
                course_id=course_id,
                original_name="测试.txt",
                stored_name=f"{document_id}.txt",
                file_type="txt",
                file_size=4,
                sha256="a" * 64,
            )
        )
        await session.commit()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        upload_dir=tmp_path / "uploads",
        qdrant_path=tmp_path / "qdrant",
        auto_index_documents=False,
    )
    manager = DocumentIndexingManager(settings, session_factory)
    manager._pipeline = cast(DocumentIndexingPipeline, pipeline)
    return manager, session_factory, engine, document_id


async def test_runtime_advances_pending_to_completed(tmp_path: Path) -> None:
    pipeline = FakePipeline()
    manager, session_factory, engine, document_id = await _runtime(tmp_path, pipeline)
    try:
        await manager.run(document_id)
        async with session_factory() as session:
            document = await session.get_one(Document, document_id)
            assert document.status is DocumentStatus.COMPLETED
            assert document.error_message is None
            assert document.progress_percent == 100
            assert document.processing_stage is DocumentProcessingStage.COMPLETED
            assert document.progress_detail == "处理完成"
        assert pipeline.indexed == [document_id]
        assert pipeline.cleaned == []
    finally:
        await manager.close()
        await engine.dispose()


async def test_runtime_marks_failure_and_cleans_partial_vectors(tmp_path: Path) -> None:
    pipeline = FakePipeline(EmptyDocumentError("empty"))
    manager, session_factory, engine, document_id = await _runtime(tmp_path, pipeline)
    try:
        await manager.run(document_id)
        async with session_factory() as session:
            document = await session.get_one(Document, document_id)
            assert document.status is DocumentStatus.FAILED
            assert document.progress_percent == 35
            assert document.processing_stage is DocumentProcessingStage.PARSING
            assert document.progress_detail == "正在解析测试资料失败"
            assert document.error_message == (
                "没有识别到可入库的文字内容。请确认文件不是空白内容；"
                "若为扫描 PDF，请换用更清晰的版本后重新上传。"
            )
        assert pipeline.cleaned == [document_id]
    finally:
        await manager.close()
        await engine.dispose()


def test_failure_message_explains_encrypted_pdf_action() -> None:
    message = friendly_indexing_error(
        InvalidDocumentFormatError("Encrypted PDF files are not supported.")
    )

    assert "已加密" in message
    assert "移除打开密码" in message
    assert "重新上传" in message
