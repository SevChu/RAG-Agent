from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.generation import AnswerStatus, AnswerStyle


class CourseAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer_style: AnswerStyle = AnswerStyle.BALANCED
    document_ids: list[UUID] | None = Field(default=None, max_length=50)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question cannot be blank")
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


class AnswerCitationRead(BaseModel):
    source_id: int
    retrieval_rank: int
    score: float
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


class AnswerRetrievalRead(BaseModel):
    retrieval_mode: str = "dense"
    requested_top_k: int
    returned_count: int
    eligible_evidence_count: int
    scope_document_count: int
    embedding_device: str | None
    fallback_reason: str | None


class AnswerTokenUsageRead(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CourseAnswerRead(BaseModel):
    course_id: UUID
    question: str
    answer: str
    status: AnswerStatus
    answer_style: AnswerStyle
    model: str | None
    elapsed_ms: float
    citations: list[AnswerCitationRead]
    retrieval: AnswerRetrievalRead
    usage: AnswerTokenUsageRead | None


class LLMConfigurationRead(BaseModel):
    provider: str
    base_url: str
    model: str
    available_models: list[str]
    configured: bool
    answer_styles: list[AnswerStyle]
