from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EmbeddingDevice(StrEnum):
    AUTO = "auto"
    CUDA = "cuda"
    CPU = "cpu"


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...]
    device: str
    fallback_reason: str | None = None
    def __post_init__(self) -> None:
        if not self.vectors:
            raise ValueError("An embedding batch cannot be empty.")
        if not self.device.strip():
            raise ValueError("Embedding device cannot be blank.")


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    point_id: str
    score: float
    course_id: str
    document_id: str
    chunk_index: int
    text: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IndexingResult:
    course_id: str
    document_id: str
    chunk_count: int
    vector_dimension: int
    device: str
    fallback_reason: str | None = None
