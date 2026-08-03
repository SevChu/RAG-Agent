from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.models import VectorSearchResult


@dataclass(frozen=True, slots=True)
class DenseRetrievalResult:
    """One course-scoped dense retrieval run and its runtime metadata."""

    query: str
    hits: tuple[VectorSearchResult, ...]
    embedding_device: str | None
    fallback_reason: str | None = None

