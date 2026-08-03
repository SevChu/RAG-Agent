from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Conversation, ConversationKind, Message


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        course_id: UUID,
        title: str,
    ) -> Conversation:
        conversation = Conversation(
            kind=ConversationKind.COURSE,
            course_id=course_id,
            title=title,
        )
        self.session.add(conversation)
        await self.session.flush()
        await self.session.refresh(conversation)
        return conversation

    async def get_course_conversation(
        self,
        *,
        conversation_id: UUID,
        course_id: UUID,
        with_messages: bool = False,
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.course_id == course_id,
            Conversation.kind == ConversationKind.COURSE,
        )
        if with_messages:
            statement = statement.options(selectinload(Conversation.messages))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_for_course(self, course_id: UUID) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(
                Conversation.course_id == course_id,
                Conversation.kind == ConversationKind.COURSE,
            )
            .order_by(
                Conversation.last_message_at.desc().nullslast(),
                Conversation.created_at.desc(),
            )
        )
        return list(result.scalars())

    async def list_course_conversations(self) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.kind == ConversationKind.COURSE)
            .options(selectinload(Conversation.course))
            .order_by(
                Conversation.last_message_at.desc().nullslast(),
                Conversation.created_at.desc(),
            )
        )
        return list(result.scalars())

    async def next_sequence_number(self, conversation_id: UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(Message.sequence_number), 0)).where(
                Message.conversation_id == conversation_id
            )
        )
        return int(result.scalar_one()) + 1

    async def delete(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
        await self.session.flush()
