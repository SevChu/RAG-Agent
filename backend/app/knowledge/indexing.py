from __future__ import annotations

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
    ) -> IndexingResult:
        batch = self.embedder.embed([chunk.text for chunk in result.chunks])
        written = self.store.replace_document(
            course_id=course_id,
            document_id=document_id,
            chunks=result.chunks,
            vectors=batch.vectors,
        )
        return IndexingResult(
            course_id=course_id,
            document_id=document_id,
            chunk_count=written,
            vector_dimension=self.embedder.dimension,
            device=batch.device,
            fallback_reason=batch.fallback_reason,
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
