from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ERROR_MAPPING
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ConflictError,
    DomainError,
    IndexStorageError,
    InvalidInputError,
)
from app.db.session import get_session
from app.generation import (
    AnswerStyle,
    ChatCompletionGateway,
    GroundedAnswer,
    GroundedAnswerGenerator,
    QueryRewriter,
    bounded_history,
    get_chat_completion_gateway,
    quick_chat_prompt,
)
from app.indexing import DocumentIndexingManager, get_indexing_manager
from app.knowledge.models import VectorSearchResult
from app.models import Conversation, DocumentStatus
from app.schemas.api import APIResponse
from app.schemas.qa import (
    AnswerCitationRead,
    AnswerRetrievalRead,
    AnswerTokenUsageRead,
    CourseAnswerRead,
    CourseAnswerRequest,
    ExternalSearchRead,
    LLMConfigurationRead,
    QuickChatRequest,
)
from app.services import ConversationService, CourseService, DocumentService

router = APIRouter(tags=["question-answering"])
_SSE_DELTA_INTERVAL_SECONDS = 0.015

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
IndexingDependency = Annotated[DocumentIndexingManager, Depends(get_indexing_manager)]
LLMDependency = Annotated[ChatCompletionGateway, Depends(get_chat_completion_gateway)]


@dataclass(frozen=True, slots=True)
class _CourseAnswerWork:
    answer: GroundedAnswer
    citations: list[AnswerCitationRead]
    retrieval: AnswerRetrievalRead
    usage: AnswerTokenUsageRead | None
    elapsed_ms: float


@router.get("/llm/config", response_model=APIResponse[LLMConfigurationRead])
async def read_llm_configuration(
    settings: SettingsDependency,
) -> APIResponse[LLMConfigurationRead]:
    return APIResponse(
        data=LLMConfigurationRead(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            available_models=settings.available_models,
            configured=bool(settings.llm_api_key.strip()),
            answer_styles=list(AnswerStyle),
            rag_context_max_messages=settings.rag_context_max_messages,
            quick_chat_context_max_messages=settings.quick_chat_context_max_messages,
            external_search_enabled=settings.external_search_enabled,
        )
    )


@router.post(
    "/courses/{course_id}/answers",
    response_model=APIResponse[CourseAnswerRead],
)
async def answer_course_question(
    course_id: UUID,
    payload: CourseAnswerRequest,
    session: SessionDependency,
    settings: SettingsDependency,
    indexing: IndexingDependency,
    llm: LLMDependency,
) -> APIResponse[CourseAnswerRead]:
    conversation, selected_model = await _resolve_course_request(
        course_id=course_id,
        payload=payload,
        session=session,
        settings=settings,
    )
    service = ConversationService(session)
    work = await _prepare_course_answer(
        course_id=course_id,
        conversation=conversation,
        payload=payload,
        selected_model=selected_model,
        session=session,
        settings=settings,
        indexing=indexing,
        llm=llm,
    )
    result = await _persist_course_answer(
        course_id=course_id,
        conversation=conversation,
        payload=payload,
        work=work,
        service=service,
    )
    return APIResponse(data=result)


@router.post("/courses/{course_id}/answers/stream")
async def stream_course_answer(
    course_id: UUID,
    payload: CourseAnswerRequest,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    indexing: IndexingDependency,
    llm: LLMDependency,
) -> StreamingResponse:
    conversation, selected_model = await _resolve_course_request(
        course_id=course_id,
        payload=payload,
        session=session,
        settings=settings,
    )
    service = ConversationService(session)

    async def events() -> AsyncIterator[str]:
        yield _sse(
            "start",
            {
                "conversation_id": str(conversation.id),
                "model": selected_model,
                "context_max_messages": settings.rag_context_max_messages,
            },
        )
        try:
            work = await _prepare_course_answer(
                course_id=course_id,
                conversation=conversation,
                payload=payload,
                selected_model=selected_model,
                session=session,
                settings=settings,
                indexing=indexing,
                llm=llm,
            )
            for delta in _text_chunks(work.answer.answer):
                if await request.is_disconnected():
                    return
                yield _sse("delta", {"text": delta})
                await asyncio.sleep(_SSE_DELTA_INTERVAL_SECONDS)
            if await request.is_disconnected():
                return
            yield _sse(
                "citations",
                {"citations": [item.model_dump(mode="json") for item in work.citations]},
            )
            result = await _persist_course_answer(
                course_id=course_id,
                conversation=conversation,
                payload=payload,
                work=work,
                service=service,
            )
            yield _sse("complete", result.model_dump(mode="json"))
        except DomainError as error:
            yield _error_event(error)
        except Exception:
            await session.rollback()
            yield _sse(
                "error",
                {"code": "INTERNAL_ERROR", "message": "流式回答失败，请重试。"},
            )

    return _streaming_response(events())


@router.post("/quick-conversations/{conversation_id}/messages/stream")
async def stream_quick_chat_message(
    conversation_id: UUID,
    payload: QuickChatRequest,
    request: Request,
    session: SessionDependency,
    settings: SettingsDependency,
    llm: LLMDependency,
) -> StreamingResponse:
    selected_model = _selected_model(payload.model, settings)
    service = ConversationService(session)
    conversation = await service.get_quick_conversation(conversation_id=conversation_id)

    async def events() -> AsyncIterator[str]:
        yield _sse(
            "start",
            {
                "conversation_id": str(conversation.id),
                "model": selected_model,
                "context_max_messages": settings.quick_chat_context_max_messages,
            },
        )
        try:
            started_at = perf_counter()
            recent = await service.recent_completed_messages(
                conversation.id,
                limit=settings.quick_chat_context_max_messages,
            )
            history = bounded_history(
                recent,
                max_messages=settings.quick_chat_context_max_messages,
                max_chars=settings.quick_chat_context_max_chars,
            )
            completion = await llm.complete_text(
                system_prompt=(
                    "你是通用快速对话助手。当前功能不检索课程资料，也不使用 Web Search。"
                    "不要声称回答来自课程知识库；如信息不确定，应明确说明。"
                ),
                user_prompt=quick_chat_prompt(payload.message, history),
                model=selected_model,
            )
            for delta in _text_chunks(completion.content):
                if await request.is_disconnected():
                    return
                yield _sse("delta", {"text": delta})
                await asyncio.sleep(_SSE_DELTA_INTERVAL_SECONDS)
            if await request.is_disconnected():
                return
            usage = (
                {
                    "prompt_tokens": completion.usage.prompt_tokens,
                    "completion_tokens": completion.usage.completion_tokens,
                    "total_tokens": completion.usage.total_tokens,
                }
                if completion.usage is not None
                else None
            )
            elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
            user_message, assistant_message = await service.record_exchange(
                conversation=conversation,
                question=payload.message,
                answer=completion.content,
                answer_status=None,
                answer_style=None,
                model=completion.model,
                citations=[],
                retrieval=None,
                usage=usage,
                elapsed_ms=elapsed_ms,
            )
            yield _sse(
                "complete",
                {
                    "conversation_id": str(conversation.id),
                    "user_message_id": str(user_message.id),
                    "assistant_message_id": str(assistant_message.id),
                    "model": completion.model,
                    "usage": usage,
                    "elapsed_ms": elapsed_ms,
                    "context_message_count": len(history),
                },
            )
        except DomainError as error:
            yield _error_event(error)
        except Exception:
            await session.rollback()
            yield _sse(
                "error",
                {"code": "INTERNAL_ERROR", "message": "快速对话失败，请重试。"},
            )

    return _streaming_response(events())


async def _resolve_course_request(
    *,
    course_id: UUID,
    payload: CourseAnswerRequest,
    session: AsyncSession,
    settings: Settings,
) -> tuple[Conversation, str]:
    await CourseService(session).get(course_id)
    selected_model = _selected_model(payload.model, settings)
    service = ConversationService(session)
    if payload.conversation_id is None:
        conversation = await service.create_course_conversation(course_id=course_id)
    else:
        conversation = await service.get_course_conversation(
            course_id=course_id,
            conversation_id=payload.conversation_id,
        )
    return conversation, selected_model


def _selected_model(requested: str | None, settings: Settings) -> str:
    selected = requested or settings.llm_model
    if selected not in settings.available_models:
        raise InvalidInputError(
            f"不支持模型 {selected}。可选模型：{', '.join(settings.available_models)}"
        )
    return selected


async def _prepare_course_answer(
    *,
    course_id: UUID,
    conversation: Conversation,
    payload: CourseAnswerRequest,
    selected_model: str,
    session: AsyncSession,
    settings: Settings,
    indexing: DocumentIndexingManager,
    llm: ChatCompletionGateway,
) -> _CourseAnswerWork:
    started_at = perf_counter()
    conversation_service = ConversationService(session)
    recent = await conversation_service.recent_completed_messages(
        conversation.id,
        limit=settings.rag_context_max_messages,
    )
    history = bounded_history(
        recent,
        max_messages=settings.rag_context_max_messages,
        max_chars=settings.rag_context_max_chars,
    )
    rewritten_query, _ = await QueryRewriter(llm).rewrite(
        question=payload.question,
        history=history,
        model=selected_model,
    )

    document_service = DocumentService(session)
    if payload.document_ids is None:
        candidate_documents = await document_service.list_for_course(course_id)
    else:
        candidate_documents = await document_service.get_many_for_course(
            course_id=course_id,
            document_ids=payload.document_ids,
        )
        unavailable = [
            document.original_name
            for document in candidate_documents
            if document.status is not DocumentStatus.COMPLETED
        ]
        if unavailable:
            raise ConflictError(
                "Only completed documents can be used for answers. Unavailable: "
                + ", ".join(unavailable)
            )

    ready_document_ids = [
        str(document.id)
        for document in candidate_documents
        if document.status is DocumentStatus.COMPLETED
    ]
    try:
        retrieval = await indexing.answer_search(
            course_id=course_id,
            query=rewritten_query,
            candidate_k=settings.rag_answer_candidate_k,
            top_k=settings.rag_answer_top_k,
            document_ids=ready_document_ids,
        )
    except (FileNotFoundError, RuntimeError, OSError) as error:
        raise IndexStorageError(
            "问答检索暂时不可用，请检查本地 Embedding、Reranker 模型与 Qdrant 存储后重试。"
        ) from error

    answer, eligible_hits = await GroundedAnswerGenerator(
        llm,
        min_similarity_score=settings.rag_min_similarity_score,
    ).answer(
        question=payload.question,
        standalone_question=rewritten_query,
        hits=retrieval.hits,
        style=payload.answer_style,
        model=selected_model,
    )
    citations = [
        _citation_read(
            source_id=source_id,
            retrieval_rank=_retrieval_rank(retrieval.hits, eligible_hits[source_id - 1]),
            result=eligible_hits[source_id - 1],
        )
        for source_id in answer.used_source_ids
    ]
    usage = (
        AnswerTokenUsageRead(
            prompt_tokens=answer.usage.prompt_tokens,
            completion_tokens=answer.usage.completion_tokens,
            total_tokens=answer.usage.total_tokens,
        )
        if answer.usage is not None
        else None
    )
    retrieval_read = AnswerRetrievalRead(
        requested_top_k=settings.rag_answer_top_k,
        candidate_top_k=settings.rag_answer_candidate_k,
        candidate_count=retrieval.dense_candidate_count,
        returned_count=len(retrieval.hits),
        eligible_evidence_count=len(eligible_hits),
        rejected_evidence_count=retrieval.rejected_evidence_count,
        scope_document_count=len(ready_document_ids),
        embedding_device=retrieval.embedding_device,
        reranker_device=retrieval.reranker_device,
        fallback_reason=retrieval.fallback_reason,
        original_question=payload.question,
        rewritten_query=rewritten_query,
        context_message_count=len(history),
        rewrite_applied=rewritten_query != payload.question,
        answer_scope=payload.answer_scope,
        external_search=ExternalSearchRead(
            failure_reason=(
                "仅课程资料模式已关闭外部检索。"
                if payload.answer_scope.value == "course_only"
                else "Day 1 已建立外部检索基础；混合检索编排将在 Day 2 接入回答链路。"
            )
        ),
    )
    return _CourseAnswerWork(
        answer=answer,
        citations=citations,
        retrieval=retrieval_read,
        usage=usage,
        elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
    )


async def _persist_course_answer(
    *,
    course_id: UUID,
    conversation: Conversation,
    payload: CourseAnswerRequest,
    work: _CourseAnswerWork,
    service: ConversationService,
) -> CourseAnswerRead:
    user_message, assistant_message = await service.record_exchange(
        conversation=conversation,
        question=payload.question,
        answer=work.answer.answer,
        answer_status=work.answer.status.value,
        answer_style=payload.answer_style.value,
        model=work.answer.model,
        citations=[citation.model_dump(mode="json") for citation in work.citations],
        retrieval=work.retrieval.model_dump(mode="json"),
        usage=work.usage.model_dump(mode="json") if work.usage is not None else None,
        elapsed_ms=work.elapsed_ms,
    )
    return CourseAnswerRead(
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        course_id=course_id,
        question=payload.question,
        answer=work.answer.answer,
        status=work.answer.status,
        answer_style=payload.answer_style,
        answer_scope=payload.answer_scope,
        model=work.answer.model,
        elapsed_ms=work.elapsed_ms,
        citations=work.citations,
        retrieval=work.retrieval,
        usage=work.usage,
        external_search=work.retrieval.external_search,
    )


def _streaming_response(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _error_event(error: DomainError) -> str:
    _, code = ERROR_MAPPING.get(type(error), (400, "DOMAIN_ERROR"))
    return _sse("error", {"code": code, "message": str(error)})


def _text_chunks(text: str, size: int = 24) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def _retrieval_rank(
    all_hits: tuple[VectorSearchResult, ...],
    target: VectorSearchResult,
) -> int:
    return next(
        rank for rank, hit in enumerate(all_hits, start=1) if hit.point_id == target.point_id
    )


def _citation_read(
    *,
    source_id: int,
    retrieval_rank: int,
    result: VectorSearchResult,
) -> AnswerCitationRead:
    payload = result.payload
    return AnswerCitationRead(
        source_id=source_id,
        source_type="course",
        retrieval_rank=retrieval_rank,
        score=result.score,
        dense_score=_optional_float(payload.get("dense_score")),
        reranker_score=_optional_float(payload.get("reranker_score")),
        content_role=str(payload.get("content_role", "unknown")),
        document_id=UUID(result.document_id),
        chunk_index=result.chunk_index,
        text=result.text,
        file_name=str(payload.get("file_name", "")),
        file_type=str(payload.get("file_type", "")),
        section_path=[str(value) for value in payload.get("section_path", [])],
        page_numbers=[int(value) for value in payload.get("page_numbers", [])],
        slide_numbers=[int(value) for value in payload.get("slide_numbers", [])],
        line_start=_optional_int(payload.get("line_start")),
        line_end=_optional_int(payload.get("line_end")),
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, (int, str)):
        return int(value)
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, (float, int, str)):
        return float(value)
    return None
