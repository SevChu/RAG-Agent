from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import SessionFactory
from app.ingestion.chunking import ChunkingContext, StructuredDocumentChunker
from app.ingestion.errors import (
    DocumentReadError,
    EmptyDocumentError,
    InvalidDocumentEncodingError,
    InvalidDocumentFormatError,
    UnsupportedParserError,
)
from app.ingestion.registry import build_default_registry
from app.knowledge.embedding import BgeM3Embedder
from app.knowledge.indexing import KnowledgeIndexer
from app.knowledge.vector_store import QdrantChunkStore
from app.models import Document, DocumentProcessingStage, DocumentStatus
from app.retrieval import (
    BgeReranker,
    DenseRetrievalResult,
    DenseRetriever,
    RerankedRetrievalResult,
)

logger = logging.getLogger(__name__)

IndexingProgressCallback = Callable[[DocumentProcessingStage, int, str], None]


@dataclass(frozen=True, slots=True)
class IndexingDocument:
    id: UUID
    course_id: UUID
    original_name: str
    stored_name: str
    file_type: str


class DocumentIndexingPipeline:
    """Synchronous local parse, chunk, embed, and Qdrant pipeline."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = build_default_registry(
            ocr_model_root=settings.paddle_ocr_base_dir,
        )
        self.chunker = StructuredDocumentChunker()
        self.embedder = BgeM3Embedder(
            settings.embedding_model_path,
            device=settings.embedding_device,
            batch_size=settings.embedding_batch_size,
        )
        self.store = QdrantChunkStore(
            settings.qdrant_path,
            collection_name=settings.qdrant_collection_name,
        )
        self.indexer = KnowledgeIndexer(self.embedder, self.store)
        self.retriever = DenseRetriever(self.embedder, self.store)
        self.reranker = BgeReranker(
            settings.reranker_model_path,
            device=settings.reranker_device,
            batch_size=settings.reranker_batch_size,
            max_length=settings.reranker_max_length,
        )

    def index(
        self,
        document: IndexingDocument,
        progress_callback: IndexingProgressCallback | None = None,
    ) -> int:
        self._report(
            progress_callback,
            DocumentProcessingStage.PREPARING,
            2,
            "正在检查原文件",
        )
        source_path = (
            self.settings.upload_dir
            / str(document.course_id)
            / document.stored_name
        )
        if not source_path.is_file():
            raise FileNotFoundError(f"Uploaded source file is missing: {source_path}")
        self._report(
            progress_callback,
            DocumentProcessingStage.PARSING,
            5,
            "正在读取文档内容",
        )
        parsed = self.registry.parse(
            source_path,
            file_type=document.file_type,
            display_name=document.original_name,
            progress_callback=(
                lambda current, total, detail: self._report_fraction(
                    progress_callback,
                    DocumentProcessingStage.PARSING,
                    current,
                    total,
                    start_percent=5,
                    end_percent=55,
                    detail=detail,
                )
            ),
        )
        self._report(
            progress_callback,
            DocumentProcessingStage.CHUNKING,
            58,
            "正在进行结构化分块",
        )
        chunks = self.chunker.chunk(
            parsed,
            context=ChunkingContext(
                course_id=str(document.course_id),
                document_id=str(document.id),
            ),
        )
        self._report(
            progress_callback,
            DocumentProcessingStage.CHUNKING,
            65,
            f"已生成 {len(chunks.chunks)} 个文本块",
        )
        result = self.indexer.index(
            chunks,
            course_id=str(document.course_id),
            document_id=str(document.id),
            embedding_progress=lambda current, total: self._report_fraction(
                progress_callback,
                DocumentProcessingStage.EMBEDDING,
                current,
                total,
                start_percent=65,
                end_percent=92,
                detail=f"正在向量化 {current}/{total} 个文本块",
            ),
            storage_progress=lambda current, total: self._report_fraction(
                progress_callback,
                DocumentProcessingStage.STORING,
                current,
                total,
                start_percent=92,
                end_percent=99,
                detail=f"正在写入知识库 {current}/{total} 个文本块",
            ),
        )
        self._report(
            progress_callback,
            DocumentProcessingStage.STORING,
            99,
            "正在确认索引结果",
        )
        return result.chunk_count

    @staticmethod
    def _report(
        callback: IndexingProgressCallback | None,
        stage: DocumentProcessingStage,
        percent: int,
        detail: str,
    ) -> None:
        if callback is not None:
            callback(stage, percent, detail)

    @classmethod
    def _report_fraction(
        cls,
        callback: IndexingProgressCallback | None,
        stage: DocumentProcessingStage,
        current: int,
        total: int,
        *,
        start_percent: int,
        end_percent: int,
        detail: str,
    ) -> None:
        safe_total = max(total, 1)
        safe_current = min(max(current, 0), safe_total)
        percent = start_percent + round(
            (end_percent - start_percent) * safe_current / safe_total
        )
        cls._report(callback, stage, percent, detail)

    def delete_document(self, *, course_id: UUID, document_id: UUID) -> None:
        self.store.delete_document(
            course_id=str(course_id),
            document_id=str(document_id),
        )

    def delete_course(self, *, course_id: UUID) -> None:
        self.store.delete_course(course_id=str(course_id))

    def search(
        self,
        *,
        course_id: UUID,
        query: str,
        top_k: int,
        document_ids: list[str],
    ) -> DenseRetrievalResult:
        return self.retriever.search(
            course_id=str(course_id),
            query=query,
            top_k=top_k,
            document_ids=document_ids,
        )

    def answer_search(
        self,
        *,
        course_id: UUID,
        query: str,
        candidate_k: int,
        top_k: int,
        document_ids: list[str],
    ) -> RerankedRetrievalResult:
        dense = self.search(
            course_id=course_id,
            query=query,
            top_k=candidate_k,
            document_ids=document_ids,
        )
        return self.reranker.rerank(dense, top_k=top_k)

    def close(self) -> None:
        self.store.close()


class DocumentIndexingManager:
    """Owns one local model/Qdrant runtime and serializes index mutations."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self._operation_lock = asyncio.Lock()
        self._pipeline: DocumentIndexingPipeline | None = None
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    def schedule(self, document_id: UUID) -> bool:
        existing = self._tasks.get(document_id)
        if existing is not None and not existing.done():
            return False
        task = asyncio.create_task(
            self.run(document_id),
            name=f"index-document-{document_id}",
        )
        self._tasks[document_id] = task
        task.add_done_callback(partial(self._finish_task, document_id))
        return True

    async def run(self, document_id: UUID) -> None:
        async with self._operation_lock:
            document = await self._begin(document_id)
            if document is None:
                return
            try:
                loop = asyncio.get_running_loop()

                def report_progress(
                    stage: DocumentProcessingStage,
                    percent: int,
                    detail: str,
                ) -> None:
                    future = asyncio.run_coroutine_threadsafe(
                        self._update_progress(document_id, stage, percent, detail),
                        loop,
                    )
                    try:
                        future.result()
                    except Exception:
                        logger.warning(
                            "Unable to persist indexing progress for %s",
                            document_id,
                            exc_info=True,
                        )

                chunk_count = await asyncio.to_thread(
                    self._get_pipeline().index,
                    document,
                    report_progress,
                )
            except asyncio.CancelledError:
                await self._mark_pending_after_interruption(document_id)
                raise
            except Exception as error:
                logger.exception("Document indexing failed for %s", document_id)
                try:
                    await asyncio.to_thread(
                        self._get_pipeline().delete_document,
                        course_id=document.course_id,
                        document_id=document.id,
                    )
                except Exception:
                    logger.exception(
                        "Partial vector cleanup failed for document %s",
                        document_id,
                    )
                await self._mark_failed(document_id, friendly_indexing_error(error))
                return
            await self._mark_completed(document_id)
            logger.info(
                "Document %s indexed successfully with %s chunks",
                document_id,
                chunk_count,
            )

    async def recover_incomplete(self) -> int:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Document).where(
                    Document.status.in_(
                        (DocumentStatus.PENDING, DocumentStatus.PROCESSING)
                    )
                )
            )
            documents = list(result.scalars())
            for document in documents:
                document.status = DocumentStatus.PENDING
                document.error_message = None
                document.progress_percent = 0
                document.processing_stage = DocumentProcessingStage.WAITING
                document.progress_detail = "等待后台恢复处理"
            await session.commit()
        for document in documents:
            self.schedule(document.id)
        return len(documents)

    async def delete_document_vectors(
        self,
        *,
        course_id: UUID,
        document_id: UUID,
    ) -> None:
        async with self._operation_lock:
            await asyncio.to_thread(
                self._get_pipeline().delete_document,
                course_id=course_id,
                document_id=document_id,
            )

    async def delete_course_vectors(self, *, course_id: UUID) -> None:
        async with self._operation_lock:
            await asyncio.to_thread(
                self._get_pipeline().delete_course,
                course_id=course_id,
            )

    async def search(
        self,
        *,
        course_id: UUID,
        query: str,
        top_k: int,
        document_ids: list[str],
    ) -> DenseRetrievalResult:
        """Serialize reads with local Qdrant mutations and keep model work off the loop."""

        async with self._operation_lock:
            return await asyncio.to_thread(
                self._get_pipeline().search,
                course_id=course_id,
                query=query,
                top_k=top_k,
                document_ids=document_ids,
            )

    async def answer_search(
        self,
        *,
        course_id: UUID,
        query: str,
        candidate_k: int,
        top_k: int,
        document_ids: list[str],
    ) -> RerankedRetrievalResult:
        """Retrieve broad candidates, rerank them, and reject unsafe evidence roles."""

        async with self._operation_lock:
            return await asyncio.to_thread(
                self._get_pipeline().answer_search,
                course_id=course_id,
                query=query,
                candidate_k=candidate_k,
                top_k=top_k,
                document_ids=document_ids,
            )

    async def close(self) -> None:
        active = [task for task in self._tasks.values() if not task.done()]
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        if self._pipeline is not None:
            await asyncio.to_thread(self._pipeline.close)

    def _get_pipeline(self) -> DocumentIndexingPipeline:
        if self._pipeline is None:
            self._pipeline = DocumentIndexingPipeline(self.settings)
        return self._pipeline

    async def _begin(self, document_id: UUID) -> IndexingDocument | None:
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None or document.status is not DocumentStatus.PENDING:
                return None
            document.status = DocumentStatus.PROCESSING
            document.error_message = None
            document.progress_percent = 1
            document.processing_stage = DocumentProcessingStage.PREPARING
            document.progress_detail = "后台任务已开始"
            await session.commit()
            return IndexingDocument(
                id=document.id,
                course_id=document.course_id,
                original_name=document.original_name,
                stored_name=document.stored_name,
                file_type=document.file_type,
            )

    async def _mark_completed(self, document_id: UUID) -> None:
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None or document.status is not DocumentStatus.PROCESSING:
                return
            document.status = DocumentStatus.COMPLETED
            document.error_message = None
            document.progress_percent = 100
            document.processing_stage = DocumentProcessingStage.COMPLETED
            document.progress_detail = "处理完成"
            await session.commit()

    async def _mark_failed(self, document_id: UUID, message: str) -> None:
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None or document.status is not DocumentStatus.PROCESSING:
                return
            document.status = DocumentStatus.FAILED
            document.error_message = message
            document.progress_detail = f"{document.progress_detail or '处理过程中'}失败"
            await session.commit()

    async def _mark_pending_after_interruption(self, document_id: UUID) -> None:
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None or document.status is not DocumentStatus.PROCESSING:
                return
            document.status = DocumentStatus.PENDING
            document.error_message = None
            document.progress_percent = 0
            document.processing_stage = DocumentProcessingStage.WAITING
            document.progress_detail = "等待后台恢复处理"
            await session.commit()

    async def _update_progress(
        self,
        document_id: UUID,
        stage: DocumentProcessingStage,
        percent: int,
        detail: str,
    ) -> None:
        async with self.session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None or document.status is not DocumentStatus.PROCESSING:
                return
            bounded_percent = min(max(percent, 1), 99)
            if bounded_percent < document.progress_percent:
                return
            if (
                bounded_percent == document.progress_percent
                and stage == document.processing_stage
                and detail == document.progress_detail
            ):
                return
            document.progress_percent = bounded_percent
            document.processing_stage = stage
            document.progress_detail = detail[:255]
            await session.commit()

    def _finish_task(
        self,
        document_id: UUID,
        task: asyncio.Task[None],
    ) -> None:
        self._tasks.pop(document_id, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Unhandled indexing task error for %s",
                document_id,
                exc_info=error,
            )


def friendly_indexing_error(error: Exception) -> str:
    """Convert internal failures into safe Chinese guidance for the material list."""

    detail = str(error).lower()
    if isinstance(error, EmptyDocumentError):
        return (
            "没有识别到可入库的文字内容。请确认文件不是空白内容；"
            "若为扫描 PDF，请换用更清晰的版本后重新上传。"
        )
    if isinstance(error, InvalidDocumentEncodingError):
        return "文本编码无法读取。请将文件另存为 UTF-8 编码后重新上传。"
    if isinstance(error, InvalidDocumentFormatError):
        if "encrypt" in detail or "password" in detail:
            return "PDF 已加密，当前无法读取。请先移除打开密码，再重新上传。"
        return "文件结构已损坏或与格式不一致。请确认文件能正常打开，再重新上传。"
    if isinstance(error, UnsupportedParserError):
        return "当前没有适用于该文件格式的解析器。请改用 PDF、DOCX、PPTX、MD 或 TXT。"
    if isinstance(error, DocumentReadError):
        if "ocr model" in detail:
            return "本地 OCR 模型不完整，扫描页暂时无法识别。请检查模型目录后重新处理。"
        if "ocr" in detail:
            return "扫描页文字识别失败。请换用更清晰、方向正确的 PDF 后重新上传。"
        return "读取文件正文时失败。请确认文件未加密且可以正常打开，再重新上传。"
    if isinstance(error, FileNotFoundError):
        if "bge-m3" in detail or "embedding" in detail:
            return "本地 Embedding 模型不完整，暂时无法建立索引。请检查模型目录后重新处理。"
        return "找不到已上传的原文件。请删除这条记录后重新上传资料。"
    if isinstance(error, (ValueError, RuntimeError)):
        return (
            "资料处理未能完成，可能是结构异常或本地模型运行失败。"
            "原文件已保留，可点击“重新处理”。"
        )
    return (
        "处理过程中出现临时运行错误。原文件已保留，可点击“重新处理”；"
        "若仍失败，请查看后端日志。"
    )


_default_manager = DocumentIndexingManager(get_settings(), SessionFactory)


def get_indexing_manager() -> DocumentIndexingManager:
    return _default_manager
