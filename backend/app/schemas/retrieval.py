from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RetrievalSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[UUID] | None = Field(default=None, max_length=50)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query cannot be blank")
        return normalized

    @field_validator("document_ids")
    @classmethod
    def document_ids_must_be_unique(
        cls,
        value: list[UUID] | None,
    ) -> list[UUID] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("document_ids cannot contain duplicates")
        return value


class RetrievalHitRead(BaseModel):
    rank: int
    score: float
    point_id: str
    document_id: UUID
    chunk_index: int
    text: str
    file_name: str
    file_type: str
    section_path: list[str]
    page_numbers: list[int]
    slide_numbers: list[int]
    line_start: int | None
    line_end: int | None


class RetrievalSearchRead(BaseModel):
    course_id: UUID
    query: str
    retrieval_mode: str = "dense"
    requested_top_k: int
    returned_count: int
    scope_document_count: int
    elapsed_ms: float
    embedding_device: str | None
    fallback_reason: str | None
    results: list[RetrievalHitRead]

