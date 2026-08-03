from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.generation import AnswerStatus, AnswerStyle


class CourseAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer_style: AnswerStyle = AnswerStyle.BALANCED
    document_ids: list[UUID] | None = Field(default=None, max_length=50)
    conversation_id: UUID | None = None
    model: str | None = Field(default=None, min_length=1, max_length=120)

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

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class AnswerCitationRead(BaseModel):
    source_id: int
    retrieval_rank: int
    score: float
    dense_score: float | None
    reranker_score: float | None
    content_role: str
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
    retrieval_mode: str = "dense_rerank"
    requested_top_k: int
    candidate_top_k: int
    candidate_count: int
    returned_count: int
    eligible_evidence_count: int
    rejected_evidence_count: int
    scope_document_count: int
    embedding_device: str | None
    reranker_device: str | None
    fallback_reason: str | None
    original_question: str = ""
    rewritten_query: str = ""
    context_message_count: int = 0
    rewrite_applied: bool = False


class AnswerTokenUsageRead(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CourseAnswerRead(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
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
    rag_context_max_messages: int
    quick_chat_context_max_messages: int


class QuickChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    model: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message cannot be blank")
        return normalized

    @field_validator("model")
    @classmethod
    def normalize_quick_model(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None
