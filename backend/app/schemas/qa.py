from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.external_search import ExternalSearchStatus
from app.generation import (
    AnswerScope,
    AnswerStatus,
    AnswerStyle,
    CitationSourceType,
    ExamPlanRead,
    ExamQualityDiagnostics,
    SummaryPlanRead,
    SummaryQualityDiagnostics,
)
from app.orchestration import CourseTaskType, SummaryScopeType


class CourseAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer_style: AnswerStyle = AnswerStyle.BALANCED
    answer_scope: AnswerScope = AnswerScope.COURSE_AND_EXTERNAL
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
    source_type: CitationSourceType = CitationSourceType.COURSE
    retrieval_rank: int | None = None
    score: float | None = None
    dense_score: float | None = None
    reranker_score: float | None = None
    content_role: str = "unknown"
    document_id: UUID | None = None
    chunk_index: int | None = None
    text: str
    file_name: str = ""
    file_type: str = ""
    section_path: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)
    slide_numbers: list[int] = Field(default_factory=list)
    line_start: int | None = None
    line_end: int | None = None
    title: str | None = None
    publisher: str | None = None
    url: str | None = None
    accessed_at: datetime | None = None


class ExternalSearchRead(BaseModel):
    triggered: bool = False
    status: ExternalSearchStatus = ExternalSearchStatus.NOT_REQUESTED
    query: str | None = None
    result_count: int = 0
    used_result_count: int = 0
    failure_reason: str | None = None
    decision_reason: str | None = None
    fallback_applied: bool = False


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
    answer_scope: AnswerScope = AnswerScope.COURSE_ONLY
    external_search: ExternalSearchRead = Field(default_factory=ExternalSearchRead)
    source_conflict_detected: bool = False
    task_type: CourseTaskType = CourseTaskType.QUESTION
    router_reason: str = ""
    summary_scope: SummaryScopeType | None = None
    summary_scope_description: str | None = None
    summary_plan: SummaryPlanRead | None = None
    summary_quality: SummaryQualityDiagnostics | None = None
    exam_plan: ExamPlanRead | None = None
    exam_quality: ExamQualityDiagnostics | None = None


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
    answer_scope: AnswerScope
    model: str | None
    elapsed_ms: float
    citations: list[AnswerCitationRead]
    retrieval: AnswerRetrievalRead
    usage: AnswerTokenUsageRead | None
    external_search: ExternalSearchRead
    task_type: CourseTaskType = CourseTaskType.QUESTION


class LLMConfigurationRead(BaseModel):
    provider: str
    base_url: str
    model: str
    available_models: list[str]
    configured: bool
    answer_styles: list[AnswerStyle]
    rag_context_max_messages: int
    quick_chat_context_max_messages: int
    external_search_enabled: bool


class QuickChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    web_search: bool = True

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
