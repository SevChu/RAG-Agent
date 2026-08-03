from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Conversation, Message, MessageRole, MessageStatus
from app.repositories import ConversationRepository, CourseRepository


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ConversationRepository(session)
        self.course_repository = CourseRepository(session)

    async def create_course_conversation(
        self,
        *,
        course_id: UUID,
        title: str | None = None,
    ) -> Conversation:
        if await self.course_repository.get(course_id) is None:
            raise NotFoundError("Course not found.")
        conversation = await self.repository.create(
            course_id=course_id,
            title=title or "新课程对话",
        )
        await self.session.commit()
        return conversation

    async def get_course_conversation(
        self,
        *,
        course_id: UUID,
        conversation_id: UUID,
        with_messages: bool = False,
    ) -> Conversation:
        conversation = await self.repository.get_course_conversation(
            course_id=course_id,
            conversation_id=conversation_id,
            with_messages=with_messages,
        )
        if conversation is None:
            raise NotFoundError("Course conversation not found.")
        return conversation

    async def list_for_course(self, course_id: UUID) -> list[Conversation]:
        if await self.course_repository.get(course_id) is None:
            raise NotFoundError("Course not found.")
        return await self.repository.list_for_course(course_id)

    async def list_all_course_conversations(self) -> list[Conversation]:
        return await self.repository.list_course_conversations()

    async def record_exchange(
        self,
        *,
        conversation: Conversation,
        question: str,
        answer: str,
        answer_status: str,
        answer_style: str,
        model: str | None,
        citations: list[dict[str, Any]],
        retrieval: dict[str, Any],
        usage: dict[str, Any] | None,
        elapsed_ms: float,
    ) -> tuple[Message, Message]:
        first_sequence = await self.repository.next_sequence_number(conversation.id)
        user_message = Message(
            conversation_id=conversation.id,
            sequence_number=first_sequence,
            role=MessageRole.USER,
            status=MessageStatus.COMPLETED,
            content=question,
            citations=[],
        )
        assistant_message = Message(
            conversation_id=conversation.id,
            sequence_number=first_sequence + 1,
            role=MessageRole.ASSISTANT,
            status=MessageStatus.COMPLETED,
            content=answer,
            answer_status=answer_status,
            answer_style=answer_style,
            model=model,
            citations=citations,
            retrieval=retrieval,
            usage=usage,
            elapsed_ms=elapsed_ms,
        )
        self.session.add_all([user_message, assistant_message])
        if first_sequence == 1:
            conversation.title = _question_title(question)
        conversation.last_message_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(user_message)
        await self.session.refresh(assistant_message)
        return user_message, assistant_message

    async def delete(self, *, course_id: UUID, conversation_id: UUID) -> Conversation:
        conversation = await self.get_course_conversation(
            course_id=course_id,
            conversation_id=conversation_id,
        )
        await self.repository.delete(conversation)
        await self.session.commit()
        return conversation


def _question_title(question: str) -> str:
    normalized = " ".join(question.split())
    return normalized if len(normalized) <= 60 else f"{normalized[:59]}…"
