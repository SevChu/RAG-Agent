from __future__ import annotations

from collections.abc import Callable

from app.ingestion.chunking import ChunkingResult
from app.knowledge.embedding import BgeM3Embedder
from app.knowledge.models import IndexingResult, VectorSearchResult
from app.knowledge.vector_store import QdrantChunkStore


class KnowledgeIndexer:
    def __init__(self, embedder: BgeM3Embedder, store: QdrantChunkStore) -> None:
        self.embedder = embedder
        self.store = store

    def index(
        self,
        result: ChunkingResult,
        *,
        course_id: str,
        document_id: str,
        embedding_progress: Callable[[int, int], None] | None = None,
        storage_progress: Callable[[int, int], None] | None = None,
    ) -> IndexingResult:
        texts = [chunk.text for chunk in result.chunks]
        vectors: list[tuple[float, ...]] = []
        device = self.embedder.active_device
        fallback_reason: str | None = None
        for start in range(0, len(texts), self.embedder.batch_size):
            end = min(start + self.embedder.batch_size, len(texts))
            batch = self.embedder.embed(texts[start:end])
            vectors.extend(batch.vectors)
            device = batch.device
            fallback_reason = batch.fallback_reason or fallback_reason
            if embedding_progress is not None:
                embedding_progress(end, len(texts))
        written = self.store.replace_document(
            course_id=course_id,
            document_id=document_id,
            chunks=result.chunks,
            vectors=vectors,
            progress_callback=storage_progress,
        )
        return IndexingResult(
            course_id=course_id,
            document_id=document_id,
            chunk_count=written,
            vector_dimension=self.embedder.dimension,
            device=device,
            fallback_reason=fallback_reason,
        )
    def search(
        self,
        query: str,
        *,
        course_id: str,
        limit: int = 10,
    ) -> tuple[VectorSearchResult, ...]:
        batch = self.embedder.embed([query])
        return self.store.search(
            course_id=course_id,
            vector=batch.vectors[0],
            limit=limit,
        )
