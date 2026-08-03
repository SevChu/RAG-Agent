from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Conversation
from app.schemas.api import APIResponse
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDeleteResult,
    ConversationDetailRead,
    ConversationMessageRead,
    ConversationSummaryRead,
)
from app.services import ConversationService, CourseService

router = APIRouter(tags=["conversations"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "/conversations",
    response_model=APIResponse[list[ConversationSummaryRead]],
)
async def list_course_conversations(
    session: SessionDependency,
) -> APIResponse[list[ConversationSummaryRead]]:
    conversations = await ConversationService(session).list_all_course_conversations()
    return APIResponse(
        data=[
            _summary(conversation, course_name=conversation.course.name)
            for conversation in conversations
            if conversation.course is not None
        ]
    )


@router.post(
    "/courses/{course_id}/conversations",
    response_model=APIResponse[ConversationSummaryRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_course_conversation(
    course_id: UUID,
    payload: ConversationCreate,
    session: SessionDependency,
) -> APIResponse[ConversationSummaryRead]:
    course = await CourseService(session).get(course_id)
    conversation = await ConversationService(session).create_course_conversation(
        course_id=course_id,
        title=payload.title,
    )
    return APIResponse(data=_summary(conversation, course_name=course.name))


@router.get(
    "/courses/{course_id}/conversations",
    response_model=APIResponse[list[ConversationSummaryRead]],
)
async def list_course_conversations_for_course(
    course_id: UUID,
    session: SessionDependency,
) -> APIResponse[list[ConversationSummaryRead]]:
    course = await CourseService(session).get(course_id)
    conversations = await ConversationService(session).list_for_course(course_id)
    return APIResponse(
        data=[_summary(conversation, course_name=course.name) for conversation in conversations]
    )


@router.get(
    "/courses/{course_id}/conversations/{conversation_id}",
    response_model=APIResponse[ConversationDetailRead],
)
async def get_course_conversation(
    course_id: UUID,
    conversation_id: UUID,
    session: SessionDependency,
) -> APIResponse[ConversationDetailRead]:
    course = await CourseService(session).get(course_id)
    conversation = await ConversationService(session).get_course_conversation(
        course_id=course_id,
        conversation_id=conversation_id,
        with_messages=True,
    )
    return APIResponse(
        data=ConversationDetailRead(
            **_summary(conversation, course_name=course.name).model_dump(),
            messages=[
                ConversationMessageRead.model_validate(message)
                for message in conversation.messages
            ],
        )
    )


@router.delete(
    "/courses/{course_id}/conversations/{conversation_id}",
    response_model=APIResponse[ConversationDeleteResult],
)
async def delete_course_conversation(
    course_id: UUID,
    conversation_id: UUID,
    session: SessionDependency,
) -> APIResponse[ConversationDeleteResult]:
    await ConversationService(session).delete(
        course_id=course_id,
        conversation_id=conversation_id,
    )
    return APIResponse(data=ConversationDeleteResult(id=conversation_id))


def _summary(
    conversation: Conversation,
    *,
    course_name: str,
) -> ConversationSummaryRead:
    if conversation.course_id is None:
        raise ValueError("Course conversation must have a course_id")
    return ConversationSummaryRead(
        id=conversation.id,
        course_id=conversation.course_id,
        course_name=course_name,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
    )
