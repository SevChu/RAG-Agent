from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.knowledge.models import EmbeddingBatch, VectorSearchResult
from app.retrieval.models import DenseRetrievalResult


class QueryEmbedder(Protocol):
    def embed(self, texts: Sequence[str]) -> EmbeddingBatch: ...


class CourseVectorStore(Protocol):
    def search(
        self,
        *,
        course_id: str,
        vector: Sequence[float],
        limit: int = 10,
        document_ids: Sequence[str] | None = None,
    ) -> tuple[VectorSearchResult, ...]: ...


class DenseRetriever:
    """Embed one query and search only the requested course/document scope."""

    def __init__(self, embedder: QueryEmbedder, store: CourseVectorStore) -> None:
        self.embedder = embedder
        self.store = store

    def search(
        self,
        *,
        course_id: str,
        query: str,
        top_k: int = 5,
        document_ids: Sequence[str] | None = None,
    ) -> DenseRetrievalResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Retrieval query cannot be blank.")
        if top_k < 1:
            raise ValueError("Retrieval top_k must be positive.")

        normalized_documents = (
            tuple(document_id.strip() for document_id in document_ids)
            if document_ids is not None
            else None
        )
        if normalized_documents == ():
            return DenseRetrievalResult(
                query=normalized_query,
                hits=(),
                embedding_device=None,
            )

        embedding = self.embedder.embed([normalized_query])
        hits = self.store.search(
            course_id=course_id,
            vector=embedding.vectors[0],
            limit=top_k,
            document_ids=normalized_documents,
        )
        return DenseRetrievalResult(
            query=normalized_query,
            hits=hits,
            embedding_device=embedding.device,
            fallback_reason=embedding.fallback_reason,
        )
