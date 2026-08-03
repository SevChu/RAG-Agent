from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.generation import AnswerStatus, AnswerStyle
from app.models import MessageRole, MessageStatus
from app.schemas.qa import (
    AnswerCitationRead,
    AnswerRetrievalRead,
    AnswerTokenUsageRead,
)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value else None


class ConversationSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    course_name: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class QuickConversationSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class ConversationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sequence_number: int
    role: MessageRole
    status: MessageStatus
    content: str
    answer_status: AnswerStatus | None
    answer_style: AnswerStyle | None
    model: str | None
    citations: list[AnswerCitationRead]
    retrieval: AnswerRetrievalRead | None
    usage: AnswerTokenUsageRead | None
    elapsed_ms: float | None
    created_at: datetime


class ConversationDetailRead(ConversationSummaryRead):
    messages: list[ConversationMessageRead]


class QuickConversationDetailRead(QuickConversationSummaryRead):
    messages: list[ConversationMessageRead]


class ConversationDeleteResult(BaseModel):
    id: UUID
    deleted: bool = True
