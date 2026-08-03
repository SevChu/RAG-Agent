from __future__ import annotations

from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, IndexStorageError, InvalidInputError
from app.db.session import get_session
from app.generation import (
    AnswerStyle,
    ChatCompletionGateway,
    GroundedAnswerGenerator,
    get_chat_completion_gateway,
)
from app.indexing import DocumentIndexingManager, get_indexing_manager
from app.knowledge.models import VectorSearchResult
from app.models import DocumentStatus
from app.schemas.api import APIResponse
from app.schemas.qa import (
    AnswerCitationRead,
    AnswerRetrievalRead,
    AnswerTokenUsageRead,
    CourseAnswerRead,
    CourseAnswerRequest,
    LLMConfigurationRead,
)
from app.services import ConversationService, CourseService, DocumentService

router = APIRouter(tags=["question-answering"])

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
IndexingDependency = Annotated[
    DocumentIndexingManager,
    Depends(get_indexing_manager),
]
LLMDependency = Annotated[
    ChatCompletionGateway,
    Depends(get_chat_completion_gateway),
]


@router.get(
    "/llm/config",
    response_model=APIResponse[LLMConfigurationRead],
)
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
    started_at = perf_counter()
    await CourseService(session).get(course_id)
    selected_model = payload.model or settings.llm_model
    if selected_model not in settings.available_models:
        raise InvalidInputError(
            f"不支持模型 {selected_model}。可选模型：{', '.join(settings.available_models)}"
        )
    conversation_service = ConversationService(session)
    if payload.conversation_id is None:
        conversation = await conversation_service.create_course_conversation(
            course_id=course_id,
        )
    else:
        conversation = await conversation_service.get_course_conversation(
            course_id=course_id,
            conversation_id=payload.conversation_id,
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
            query=payload.question,
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
    elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
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
    )
    user_message, assistant_message = await conversation_service.record_exchange(
        conversation=conversation,
        question=payload.question,
        answer=answer.answer,
        answer_status=answer.status.value,
        answer_style=payload.answer_style.value,
        model=answer.model,
        citations=[citation.model_dump(mode="json") for citation in citations],
        retrieval=retrieval_read.model_dump(mode="json"),
        usage=usage.model_dump(mode="json") if usage is not None else None,
        elapsed_ms=elapsed_ms,
    )
    return APIResponse(
        data=CourseAnswerRead(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            course_id=course_id,
            question=payload.question,
            answer=answer.answer,
            status=answer.status,
            answer_style=payload.answer_style,
            model=answer.model,
            elapsed_ms=elapsed_ms,
            citations=citations,
            retrieval=retrieval_read,
            usage=usage,
        )
    )


def _retrieval_rank(
    all_hits: tuple[VectorSearchResult, ...],
    target: VectorSearchResult,
) -> int:
    return next(
        rank
        for rank, hit in enumerate(all_hits, start=1)
        if hit.point_id == target.point_id
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
