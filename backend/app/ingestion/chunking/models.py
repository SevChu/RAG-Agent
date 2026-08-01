from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.models import BlockKind, ParsedDocument


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    target_tokens: int = 600
    overlap_tokens: int = 80

    def __post_init__(self) -> None:
        if self.target_tokens < 1:
            raise ValueError("target_tokens must be at least 1.")
        if self.overlap_tokens < 0:
            raise ValueError("overlap_tokens cannot be negative.")
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens.")


@dataclass(frozen=True, slots=True)
class ChunkingContext:
    course_id: str | None = None
    document_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkSourceMetadata:
    course_id: str | None
    document_id: str | None
    file_name: str
    file_type: str
    parser_name: str
    section_path: tuple[str, ...]
    source_block_start: int
    source_block_end: int
    source_block_indices: tuple[int, ...]
    context_block_indices: tuple[int, ...]
    block_kinds: tuple[BlockKind, ...]
    line_start: int | None
    line_end: int | None
    page_numbers: tuple[int, ...]
    slide_numbers: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.source_block_start < 0 or self.source_block_end < self.source_block_start:
            raise ValueError("Chunk source block range is invalid.")
        if not self.source_block_indices:
            raise ValueError("A chunk must reference at least one source block.")


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    chunk_index: int
    text: str
    estimated_token_count: int
    overlap_token_count: int
    source: ChunkSourceMetadata

    def __post_init__(self) -> None:
        if self.chunk_index < 0:
            raise ValueError("chunk_index cannot be negative.")
        if not self.text.strip():
            raise ValueError("Chunk text cannot be blank.")
        if self.estimated_token_count < 1:
            raise ValueError("estimated_token_count must be positive.")
        if self.overlap_token_count < 0:
            raise ValueError("overlap_token_count cannot be negative.")


@dataclass(frozen=True, slots=True)
class ChunkWarning:
    code: str
    message: str
    section_path: tuple[str, ...]
    source_block_indices: tuple[int, ...]
    chunk_index: int | None = None


@dataclass(frozen=True, slots=True)
class ChunkingStats:
    source_block_count: int
    covered_source_blocks: int
    uncovered_source_blocks: int
    chunk_count: int
    min_estimated_tokens: int
    max_estimated_tokens: int
    average_estimated_tokens: float
    chunks_with_overlap: int
    average_overlap_tokens: float
    over_target_chunks: int
    protected_over_target_units: int
    anomaly_count: int


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    document: ParsedDocument
    config: ChunkingConfig
    chunks: tuple[DocumentChunk, ...]
    stats: ChunkingStats
    warnings: tuple[ChunkWarning, ...] = ()

    def __post_init__(self) -> None:
        if not self.chunks:
            raise ValueError("Chunking must produce at least one chunk.")
        indexes = [chunk.chunk_index for chunk in self.chunks]
        if indexes != list(range(len(self.chunks))):
            raise ValueError("Chunk indexes must be contiguous and zero-based.")
