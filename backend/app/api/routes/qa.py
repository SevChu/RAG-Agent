from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import ResolvedAgentRuntime, resolve_agent_runtime
from app.api.errors import ERROR_MAPPING
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ConflictError,
    DomainError,
    IndexStorageError,
    InvalidInputError,
)
from app.db.session import get_session
from app.external_search import (
    ExternalSearchEvidence,
    ExternalSearchGateway,
    ExternalSearchStatus,
    get_external_search_gateway,
)
from app.generation import (
    AnswerScope,
    AnswerStatus,
    AnswerStyle,
    ChatCompletionGateway,
    CitationSourceType,
    DynamicSummaryPlanner,
    ExamPlan,
    ExamPlanRead,
    ExamQualityDiagnostics,
    GeneratedExamQuestion,
    GroundedAnswer,
    GroundedAnswerGenerator,
    GroundedExamGenerator,
    GroundedSummaryGenerator,
    QueryRewriter,
    SummaryPlan,
    SummaryPlanRead,
    SummaryQualityDiagnostics,
    bounded_history,
    build_exam_plan,
    get_chat_completion_gateway,
    quick_chat_prompt,
    quick_chat_search_query,
    quick_chat_web_search_decision,
    render_exam,
)
from app.indexing import DocumentIndexingManager, get_indexing_manager
from app.knowledge.models import VectorSearchResult
from app.models import Conversation, DocumentStatus, Message, MessageRole
from app.orchestration import (
    ConditionalAnswerGraph,
    CourseTaskType,
    RequestRoutingGraph,
    SummaryScopeType,
    exam_follow_up_output,
    summary_retrieval_query,
    summary_scope,
)
from app.retrieval import RerankedRetrievalResult
from app.schemas.api import APIResponse
from app.schemas.qa import (
    AnswerCitationRead,
    AnswerRetrievalRead,
    AnswerTokenUsageRead,
    CourseAnswerRead,
    CourseAnswerRequest,
    ExternalSearchRead,
    LLMConfigurationRead,
    LLMProviderRead,
    QuickChatRequest,
)
from app.services import ConversationService, CourseService, DocumentService

router = APIRouter(tags=["question-answering"])
_SSE_DELTA_INTERVAL_SECONDS = 0.015
_EXAM_ARTIFACT_KEY = "_exam_artifact"
_QUICK_EXTERNAL_CITATION = re.compile(r"\[外(\d+)]")

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
IndexingDependency = Annotated[DocumentIndexingManager, Depends(get_indexing_manager)]
LLMDependency = Annotated[ChatCompletionGateway, Depends(get_chat_completion_gateway)]
ExternalSearchDependency = Annotated[ExternalSearchGateway, Depends(get_external_search_gateway)]


@dataclass(frozen=True, slots=True)
class _CourseAnswerWork:
    answer: GroundedAnswer
    citations: list[AnswerCitationRead]
    retrieval: AnswerRetrievalRead
    usage: AnswerTokenUsageRead | None
    elapsed_ms: float
    task_type: CourseTaskType
    effective_scope: AnswerScope
    exam_artifact: dict[str, object] | None = None


@router.get("/llm/config", response_model=APIResponse[LLMConfigurationRead])
async def read_llm_configuration(
    settings: SettingsDependency,
) -> APIResponse[LLMConfigurationRead]:
    default_provider = settings.provider_for_model(settings.llm_model)
    return APIResponse(
        data=LLMConfigurationRead(
            provider=(default_provider.id if default_provider else settings.llm_provider),
            base_url=(default_provider.base_url if default_provider else settings.llm_base_url),
            model=settings.llm_model,
            available_models=settings.available_models,
            configured=bool(default_provider and default_provider.configured),
            answer_styles=list(AnswerStyle),
            rag_context_max_messages=settings.rag_context_max_messages,
            quick_chat_context_max_messages=settings.quick_chat_context_max_messages,
            external_search_enabled=settings.external_search_enabled,
            providers=[
                LLMProviderRead(
                    id=provider.id,
                    name=provider.name,
                    base_url=provider.base_url,
                    models=list(provider.models),
                    configured=provider.configured,
                    api_key_env=provider.api_key_env,
                    models_env=provider.models_env,
                )
                for provider in settings.llm_providers
            ],
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
    external_search: ExternalSearchDependency,
) -> APIResponse[CourseAnswerRead]:
    conversation, runtime = await _resolve_course_request(
        course_id=course_id,
        payload=payload,
        session=session,
        settings=settings,
    )
    settings = runtime.settings
    service = ConversationService(session)
    work = await _prepare_course_answer(
        course_id=course_id,
        conversation=conversation,
        payload=payload,
        runtime=runtime,
        session=session,
        settings=settings,
        indexing=indexing,
        llm=llm,
        external_search=external_search,
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
    external_search: ExternalSearchDependency,
) -> StreamingResponse:
    conversation, runtime = await _resolve_course_request(
        course_id=course_id,
        payload=payload,
        session=session,
        settings=settings,
    )
    selected_model = runtime.model
    settings = runtime.settings
    service = ConversationService(session)

    async def events() -> AsyncIterator[str]:
        yield _sse(
            "start",
            {
                "conversation_id": str(conversation.id),
                "model": selected_model,
                "context_max_messages": settings.rag_context_max_messages,
                "agent_runtime": _runtime_payload(runtime),
            },
        )
        try:
            work = await _prepare_course_answer(
                course_id=course_id,
                conversation=conversation,
                payload=payload,
                runtime=runtime,
                session=session,
                settings=settings,
                indexing=indexing,
                llm=llm,
                external_search=external_search,
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
    external_search: ExternalSearchDependency,
) -> StreamingResponse:
    service = ConversationService(session)
    conversation = await service.get_quick_conversation(conversation_id=conversation_id)
    runtime = await resolve_agent_runtime(
        session, settings, conversation=conversation, model=payload.model
    )
    selected_model = runtime.model
    settings = runtime.settings
    llm = runtime.gateway(llm)

    async def events() -> AsyncIterator[str]:
        yield _sse(
            "start",
            {
                "conversation_id": str(conversation.id),
                "model": selected_model,
                "context_max_messages": settings.quick_chat_context_max_messages,
                "agent_runtime": _runtime_payload(runtime),
                "web_search_enabled": payload.web_search and settings.external_search_enabled,
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
            if not payload.web_search:
                should_search = False
                decision_reason = "本轮已关闭联网搜索。"
            elif not settings.external_search_enabled:
                should_search = False
                decision_reason = "外部检索已由服务端配置关闭。"
            else:
                should_search, decision_reason = quick_chat_web_search_decision(
                    payload.message,
                    enabled=True,
                )
            search_query = (
                quick_chat_search_query(payload.message, history) if should_search else None
            )
            search_result = (
                await external_search.search(query=search_query, model=selected_model)
                if search_query is not None
                else None
            )
            external_evidence = (
                search_result.results
                if search_result is not None
                and search_result.status is ExternalSearchStatus.SUCCEEDED
                else ()
            )
            search_failure_reason = (
                search_result.failure_reason
                if search_result is not None and not external_evidence
                else None
            )
            external_search_read = ExternalSearchRead(
                triggered=should_search,
                status=(
                    search_result.status
                    if search_result is not None
                    else ExternalSearchStatus.NOT_REQUESTED
                ),
                query=search_query,
                result_count=len(external_evidence),
                used_result_count=len(external_evidence),
                failure_reason=search_failure_reason,
                decision_reason=decision_reason,
                fallback_applied=should_search and not external_evidence,
            )
            completion = await llm.complete_text(
                system_prompt=(
                    "你是通用快速对话助手。当前功能不检索课程资料，但可能提供经过筛选的"
                    "Web Search 证据。不要声称回答来自课程知识库，也不要声称访问了未在"
                    "证据中出现的网页；如信息不确定，应明确说明。"
                ),
                user_prompt=quick_chat_prompt(
                    payload.message,
                    history,
                    external_evidence=external_evidence,
                    search_failure_reason=search_failure_reason,
                ),
                model=selected_model,
            )
            answer_content, used_external_ids = _sanitize_quick_external_citations(
                completion.content,
                available_count=len(external_evidence),
            )
            external_search_read = external_search_read.model_copy(
                update={"used_result_count": len(used_external_ids)}
            )
            for delta in _text_chunks(answer_content):
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
            citations = [
                _external_citation_read(source_id=index, evidence=evidence)
                for index, evidence in enumerate(external_evidence, start=1)
            ]
            retrieval = AnswerRetrievalRead(
                agent_runtime=runtime.diagnostics(),
                retrieval_mode="external_web",
                requested_top_k=settings.external_search_max_results,
                candidate_top_k=settings.external_search_max_results,
                candidate_count=(search_result.raw_result_count if search_result else 0),
                returned_count=len(external_evidence),
                eligible_evidence_count=len(external_evidence),
                rejected_evidence_count=max(
                    (search_result.raw_result_count if search_result else 0)
                    - len(external_evidence),
                    0,
                ),
                scope_document_count=0,
                embedding_device=None,
                reranker_device=None,
                fallback_reason=search_failure_reason,
                original_question=payload.message,
                rewritten_query=search_query or payload.message,
                context_message_count=len(history),
                rewrite_applied=bool(search_query and search_query != payload.message),
                answer_scope=AnswerScope.COURSE_AND_EXTERNAL,
                external_search=external_search_read,
                router_reason=decision_reason,
            )
            user_message, assistant_message = await service.record_exchange(
                conversation=conversation,
                question=payload.message,
                answer=answer_content,
                answer_status=None,
                answer_style=None,
                model=completion.model,
                citations=[item.model_dump(mode="json") for item in citations],
                retrieval=retrieval.model_dump(mode="json"),
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
                    "agent_runtime": _runtime_payload(runtime),
                    "usage": usage,
                    "elapsed_ms": elapsed_ms,
                    "context_message_count": len(history),
                    "citations": [item.model_dump(mode="json") for item in citations],
                    "external_search": external_search_read.model_dump(mode="json"),
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
) -> tuple[Conversation, ResolvedAgentRuntime]:
    await CourseService(session).get(course_id)
    service = ConversationService(session, settings)
    if payload.conversation_id is None:
        # Validate before creating a conversation, including a conflicting model.
        runtime = await resolve_agent_runtime(
            session,
            settings,
            profile_id=payload.agent_profile_id,
            course_id=course_id,
            model=payload.model,
        )
        # Insert the revision selected above, without re-reading the current pointer.
        conversation = await service.create_resolved_course_conversation(
            course_id=course_id,
            runtime=runtime,
        )
    else:
        if payload.agent_profile_id is not None:
            raise InvalidInputError("已有会话不能切换智能体，请新建会话。")
        conversation = await service.get_course_conversation(
            course_id=course_id,
            conversation_id=payload.conversation_id,
        )
        runtime = await resolve_agent_runtime(
            session,
            settings,
            conversation=conversation,
            model=payload.model,
        )
    return conversation, runtime


def _runtime_payload(runtime: ResolvedAgentRuntime) -> dict[str, object] | None:
    diagnostics = runtime.diagnostics()
    return diagnostics.model_dump(mode="json") if diagnostics else None


async def _prepare_course_answer(
    *,
    course_id: UUID,
    conversation: Conversation,
    payload: CourseAnswerRequest,
    runtime: ResolvedAgentRuntime,
    session: AsyncSession,
    settings: Settings,
    indexing: DocumentIndexingManager,
    llm: ChatCompletionGateway,
    external_search: ExternalSearchGateway,
) -> _CourseAnswerWork:
    work = await _prepare_course_answer_work(
        course_id=course_id,
        conversation=conversation,
        payload=payload,
        selected_model=runtime.model,
        session=session,
        settings=runtime.settings,
        indexing=indexing,
        llm=runtime.gateway(llm),
        external_search=external_search,
    )
    return replace(
        work,
        retrieval=work.retrieval.model_copy(
            update={"agent_runtime": runtime.diagnostics()},
        ),
    )


async def _prepare_course_answer_work(
    *,
    course_id: UUID,
    conversation: Conversation,
    payload: CourseAnswerRequest,
    selected_model: str,
    session: AsyncSession,
    settings: Settings,
    indexing: DocumentIndexingManager,
    llm: ChatCompletionGateway,
    external_search: ExternalSearchGateway,
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
    previous_exam = _immediately_preceding_exam(recent)
    follow_up_output = (
        exam_follow_up_output(payload.question) if previous_exam is not None else None
    )
    if previous_exam is not None and follow_up_output is not None:
        if conversation.agent_profile_id is not None:
            for citation in previous_exam.citations:
                if citation.get("source_type") == CitationSourceType.EXTERNAL.value:
                    if (
                        payload.answer_scope is AnswerScope.COURSE_ONLY
                        or not settings.external_search_enabled
                    ):
                        raise InvalidInputError(
                            "上一份试卷包含外部来源，不能在当前范围内续写，请重新出题。"
                        )
                elif payload.document_ids is not None and str(citation.get("document_id")) not in {
                    str(document_id) for document_id in payload.document_ids
                }:
                    raise InvalidInputError("上一份试卷超出本轮指定的资料范围，请重新出题。")
        return await _prepare_persisted_exam_follow_up(
            previous=previous_exam,
            question=payload.question,
            include_answers=follow_up_output.include_answers,
            include_explanations=follow_up_output.include_explanations,
            context_message_count=len(history),
            started_at=started_at,
            course_id=course_id,
            llm=llm,
            model=selected_model,
        )

    routing = await RequestRoutingGraph().route(payload.question)
    rewritten_query, _ = await QueryRewriter(llm).rewrite(
        question=payload.question,
        history=history,
        model=selected_model,
    )

    document_service = DocumentService(session)
    all_documents = await document_service.list_for_course(course_id)
    explicit_document_scope = payload.document_ids is not None
    if payload.document_ids is None:
        candidate_documents = all_documents
        if routing.task_type in {CourseTaskType.SUMMARY, CourseTaskType.EXAM}:
            normalized_request = payload.question.casefold()
            named_documents = [
                document
                for document in candidate_documents
                if document.original_name.casefold() in normalized_request
            ]
            if named_documents:
                candidate_documents = named_documents
                explicit_document_scope = True
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

    all_ready_document_count = sum(
        document.status is DocumentStatus.COMPLETED for document in all_documents
    )
    ready_document_ids = [
        str(document.id)
        for document in candidate_documents
        if document.status is DocumentStatus.COMPLETED
    ]
    resolved_summary_scope: SummaryScopeType | None = None
    summary_scope_description: str | None = None
    retrieval_query = rewritten_query
    requested_top_k = settings.rag_answer_top_k
    candidate_top_k = settings.rag_answer_candidate_k
    summary_plan_read: SummaryPlanRead | None = None
    summary_quality: SummaryQualityDiagnostics | None = None
    exam_plan_read: ExamPlanRead | None = None
    exam_quality: ExamQualityDiagnostics | None = None
    exam_artifact: dict[str, object] | None = None
    if routing.task_type is CourseTaskType.SUMMARY:
        resolved_summary_scope, summary_scope_description = summary_scope(
            payload.question,
            explicit_document_scope=explicit_document_scope,
            selected_document_count=len(ready_document_ids),
            total_ready_document_count=all_ready_document_count,
        )
        requested_top_k = settings.rag_summary_top_k
        candidate_top_k = settings.rag_summary_candidate_k
    elif routing.task_type is CourseTaskType.EXAM:
        requested_top_k = settings.rag_exam_top_k
        candidate_top_k = settings.rag_exam_candidate_k

    external_evidence: tuple[ExternalSearchEvidence, ...] = ()
    if routing.task_type is CourseTaskType.SUMMARY:
        assert resolved_summary_scope is not None
        assert summary_scope_description is not None
        plan_result = await DynamicSummaryPlanner(llm).plan(
            request=payload.question,
            scope=resolved_summary_scope,
            scope_description=summary_scope_description,
            model=selected_model,
        )
        try:
            retrieval, section_source_ids = await _retrieve_summary_sections(
                course_id=course_id,
                plan=plan_result.plan,
                indexing=indexing,
                candidate_k=candidate_top_k,
                configured_top_k=requested_top_k,
                max_sources=settings.rag_summary_max_sources,
                max_context_chars=settings.rag_summary_context_max_chars,
                document_ids=ready_document_ids,
            )
        except (FileNotFoundError, RuntimeError, OSError) as error:
            raise IndexStorageError(
                "总结检索暂时不可用，请检查本地 Embedding、Reranker 模型与 Qdrant 存储后重试。"
            ) from error
        retrieval_query = retrieval.query
        summary_result = await GroundedSummaryGenerator(llm).summarize(
            request=payload.question,
            plan=plan_result.plan,
            hits=retrieval.hits,
            section_source_ids=section_source_ids,
            model=selected_model,
            prior_usage=plan_result.usage,
        )
        answer = summary_result.answer
        eligible_hits = summary_result.eligible_hits
        summary_plan_read = SummaryPlanRead.from_plan(plan_result.plan)
        summary_quality = summary_result.quality
        effective_scope = AnswerScope.COURSE_ONLY
        external_search_read = ExternalSearchRead(
            decision_reason="知识总结默认仅使用课程资料，未触发外部检索。"
        )
    elif routing.task_type is CourseTaskType.EXAM:
        exam_plan = build_exam_plan(
            payload.question,
            allow_external=(
                payload.answer_scope is AnswerScope.COURSE_AND_EXTERNAL
                and settings.external_search_enabled
            ),
        )
        try:
            retrieval = await indexing.exam_search(
                course_id=course_id,
                query=exam_plan.retrieval_query,
                candidate_k=candidate_top_k,
                top_k=requested_top_k,
                document_ids=ready_document_ids,
            )
        except (FileNotFoundError, RuntimeError, OSError) as error:
            raise IndexStorageError(
                "出题检索暂时不可用，请检查本地 Embedding、Reranker 模型与 Qdrant 存储后重试。"
            ) from error
        retrieval_query = retrieval.query
        exam_hits = _bounded_exam_hits(
            retrieval.hits,
            max_sources=settings.rag_exam_max_sources,
            max_context_chars=settings.rag_exam_context_max_chars,
        )
        external_result = None
        should_search_exam_external = exam_plan.allow_external and exam_plan.max_external_count > 0
        if should_search_exam_external:
            external_result = await external_search.search(
                query=(
                    f"{payload.question} 高质量课程练习题 官方或大学教学资料 "
                    f"{exam_plan.programming_language}"
                ),
                model=selected_model,
            )
            if external_result.status is ExternalSearchStatus.SUCCEEDED:
                external_evidence = external_result.results
        exam_result = await GroundedExamGenerator(llm).generate(
            request=payload.question,
            plan=exam_plan,
            course_hits=exam_hits,
            external_evidence=external_evidence,
            model=selected_model,
        )
        answer = exam_result.answer
        eligible_hits = exam_result.course_hits
        exam_plan_read = ExamPlanRead.from_plan(exam_plan)
        exam_quality = exam_result.quality
        if exam_result.questions:
            exam_artifact = {
                "version": 1,
                "plan": exam_plan.model_dump(mode="json"),
                "questions": [
                    question.model_dump(mode="json") for question in exam_result.questions
                ],
            }
        effective_scope = (
            AnswerScope.COURSE_AND_EXTERNAL if exam_plan.allow_external else AnswerScope.COURSE_ONLY
        )
        external_search_read = ExternalSearchRead(
            triggered=should_search_exam_external,
            status=(
                external_result.status
                if external_result is not None
                else ExternalSearchStatus.NOT_REQUESTED
            ),
            query=(external_result.query if external_result is not None else None),
            result_count=(len(external_result.results) if external_result is not None else 0),
            used_result_count=len(answer.used_external_source_ids),
            failure_reason=(
                external_result.failure_reason if external_result is not None else None
            ),
            decision_reason=(
                "混合组卷允许外部优质题材，但整卷外部补充题不超过 20%。"
                if should_search_exam_external
                else "本次题量按 20% 向下取整后没有外部题名额，未触发外部检索。"
                if exam_plan.allow_external
                else "本次组卷限定为课程资料，未触发外部检索。"
            ),
            fallback_applied=exam_result.quality.external_fallback_applied,
        )
    else:
        try:
            retrieval = await indexing.answer_search(
                course_id=course_id,
                query=retrieval_query,
                candidate_k=candidate_top_k,
                top_k=requested_top_k,
                document_ids=ready_document_ids,
            )
        except (FileNotFoundError, RuntimeError, OSError) as error:
            raise IndexStorageError(
                "问答检索暂时不可用，请检查本地 Embedding、Reranker 模型与 Qdrant 存储后重试。"
            ) from error
        graph_result = await ConditionalAnswerGraph(
            llm=llm,
            external_search=external_search,
            min_similarity_score=settings.rag_min_similarity_score,
            external_trigger_score=settings.external_search_trigger_score,
            external_search_enabled=settings.external_search_enabled,
            provider=settings.llm_provider,
        ).run(
            question=payload.question,
            standalone_question=rewritten_query,
            course_hits=retrieval.hits,
            style=payload.answer_style,
            scope=payload.answer_scope,
            model=selected_model,
        )
        answer = graph_result.answer
        eligible_hits = graph_result.eligible_course_hits
        external_evidence = graph_result.external_evidence
        effective_scope = payload.answer_scope
        external_result = graph_result.external_result
        external_search_read = ExternalSearchRead(
            triggered=graph_result.decision.should_search,
            status=(
                external_result.status
                if external_result is not None
                else ExternalSearchStatus.NOT_REQUESTED
            ),
            query=(external_result.query if external_result is not None else None),
            result_count=(len(external_result.results) if external_result is not None else 0),
            used_result_count=len(answer.used_external_source_ids),
            failure_reason=(
                external_result.failure_reason if external_result is not None else None
            ),
            decision_reason=graph_result.decision.reason,
            fallback_applied=graph_result.fallback_applied,
        )

    course_citations = [
        _citation_read(
            source_id=source_id,
            retrieval_rank=_retrieval_rank(retrieval.hits, eligible_hits[source_id - 1]),
            result=eligible_hits[source_id - 1],
        )
        for source_id in answer.used_source_ids
    ]
    external_citations = [
        _external_citation_read(
            source_id=source_id,
            evidence=external_evidence[source_id - 1],
        )
        for source_id in answer.used_external_source_ids
    ]
    citations = [*course_citations, *external_citations]
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
        retrieval_mode=(
            "summary_dense_rerank"
            if routing.task_type is CourseTaskType.SUMMARY
            else "exam_dense_rerank"
            if routing.task_type is CourseTaskType.EXAM
            else "dense_rerank"
        ),
        requested_top_k=requested_top_k,
        candidate_top_k=candidate_top_k,
        candidate_count=retrieval.dense_candidate_count,
        returned_count=len(retrieval.hits),
        eligible_evidence_count=len(eligible_hits),
        rejected_evidence_count=retrieval.rejected_evidence_count,
        scope_document_count=len(ready_document_ids),
        embedding_device=retrieval.embedding_device,
        reranker_device=retrieval.reranker_device,
        fallback_reason=retrieval.fallback_reason,
        original_question=payload.question,
        rewritten_query=retrieval_query,
        context_message_count=len(history),
        rewrite_applied=retrieval_query != payload.question,
        answer_scope=effective_scope,
        external_search=external_search_read,
        source_conflict_detected=answer.has_source_conflict,
        task_type=routing.task_type,
        router_reason=routing.reason,
        summary_scope=resolved_summary_scope,
        summary_scope_description=summary_scope_description,
        summary_plan=summary_plan_read,
        summary_quality=summary_quality,
        exam_plan=exam_plan_read,
        exam_quality=exam_quality,
    )
    return _CourseAnswerWork(
        answer=answer,
        citations=citations,
        retrieval=retrieval_read,
        usage=usage,
        elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
        task_type=routing.task_type,
        effective_scope=effective_scope,
        exam_artifact=exam_artifact,
    )


def _immediately_preceding_exam(messages: list[Message]) -> Message | None:
    if not messages:
        return None
    previous = messages[-1]
    if previous.role is not MessageRole.ASSISTANT or not previous.retrieval:
        return None
    if previous.retrieval.get("task_type") != CourseTaskType.EXAM.value:
        return None
    return previous


async def _prepare_persisted_exam_follow_up(
    *,
    previous: Message,
    question: str,
    include_answers: bool,
    include_explanations: bool,
    context_message_count: int,
    started_at: float,
    course_id: UUID,
    llm: ChatCompletionGateway,
    model: str,
) -> _CourseAnswerWork:
    """Re-render the same validated exam without leaking or regenerating questions."""

    assert previous.retrieval is not None
    artifact = previous.retrieval.get(_EXAM_ARTIFACT_KEY)
    if not isinstance(artifact, dict):
        return await _prepare_legacy_exam_follow_up(
            previous=previous,
            question=question,
            include_explanations=include_explanations,
            context_message_count=context_message_count,
            started_at=started_at,
            course_id=course_id,
            llm=llm,
            model=model,
        )
    try:
        plan = ExamPlan.model_validate(artifact["plan"])
        raw_questions = artifact["questions"]
        if not isinstance(raw_questions, list) or not raw_questions:
            raise ValueError("empty exam artifact")
        questions = tuple(GeneratedExamQuestion.model_validate(item) for item in raw_questions)
        previous_retrieval = AnswerRetrievalRead.model_validate(previous.retrieval)
        previous_quality = previous_retrieval.exam_quality
        if previous_quality is None:
            raise ValueError("missing exam quality")
        citations = [AnswerCitationRead.model_validate(item) for item in previous.citations]
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidInputError(
            "上一份试卷的会话工件不完整，无法安全恢复同一组题。请重新发送上一条出题指令后重试。"
        ) from error

    public_plan = plan.model_copy(
        update={
            "include_answers": include_answers,
            "include_explanations": include_answers and include_explanations,
        }
    )
    quality = previous_quality.model_copy(
        update={
            "answers_included": public_plan.include_answers,
            "explanations_included": public_plan.include_explanations,
        }
    )
    plan_read = ExamPlanRead.from_plan(public_plan)
    retrieval = previous_retrieval.model_copy(
        update={
            "retrieval_mode": "exam_artifact_replay",
            "original_question": question,
            "rewritten_query": question,
            "context_message_count": context_message_count,
            "rewrite_applied": False,
            "task_type": CourseTaskType.EXAM,
            "router_reason": (
                "检测到对紧邻上一份试卷的答案/解析续写请求，已恢复同一试卷的内部工件。"
            ),
            "exam_plan": plan_read,
            "exam_quality": quality,
        }
    )
    course_ids = tuple(
        dict.fromkeys(
            source_id
            for exam_question in questions
            for source_id in exam_question.course_source_ids
        )
    )
    external_ids = tuple(
        dict.fromkeys(
            source_id
            for exam_question in questions
            for source_id in exam_question.external_source_ids
        )
    )
    return _CourseAnswerWork(
        answer=GroundedAnswer(
            answer=render_exam(questions, public_plan),
            status=AnswerStatus.ANSWERED,
            used_source_ids=course_ids,
            used_external_source_ids=external_ids,
            model=previous.model,
        ),
        citations=citations,
        retrieval=retrieval,
        usage=None,
        elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
        task_type=CourseTaskType.EXAM,
        effective_scope=previous_retrieval.answer_scope,
        exam_artifact=dict(artifact),
    )


async def _prepare_legacy_exam_follow_up(
    *,
    previous: Message,
    question: str,
    include_explanations: bool,
    context_message_count: int,
    started_at: float,
    course_id: UUID,
    llm: ChatCompletionGateway,
    model: str,
) -> _CourseAnswerWork:
    """Answer a pre-artifact exam from its visible questions and saved evidence."""

    assert previous.retrieval is not None
    previous_retrieval = AnswerRetrievalRead.model_validate(previous.retrieval)
    previous_quality = previous_retrieval.exam_quality
    previous_plan = previous_retrieval.exam_plan
    if previous_quality is None or previous_plan is None:
        raise InvalidInputError(
            "上一份回复没有完整的试卷上下文，无法确定当前所指题目。请重新发送出题指令后重试。"
        )
    raw_course_citations = sorted(
        (
            AnswerCitationRead.model_validate(item)
            for item in previous.citations
            if item.get("source_type", CitationSourceType.COURSE.value)
            == CitationSourceType.COURSE.value
        ),
        key=lambda item: item.source_id,
    )
    if not raw_course_citations:
        raise InvalidInputError(
            "上一份旧试卷没有可恢复的课程证据，无法安全补充答案。请重新发送出题指令后重试。"
        )
    course_citations = [
        citation.model_copy(update={"source_id": index})
        for index, citation in enumerate(raw_course_citations, start=1)
    ]
    hits = tuple(
        VectorSearchResult(
            point_id=f"conversation-exam-{previous.id}-{index}",
            score=1.0,
            course_id=str(course_id),
            document_id=str(citation.document_id or UUID(int=0)),
            chunk_index=citation.chunk_index or 0,
            text=citation.text,
            payload={
                "file_name": citation.file_name,
                "file_type": citation.file_type,
                "section_path": citation.section_path,
                "page_numbers": citation.page_numbers,
                "slide_numbers": citation.slide_numbers,
                "line_start": citation.line_start,
                "line_end": citation.line_end,
                "content_role": citation.content_role,
            },
        )
        for index, citation in enumerate(course_citations, start=1)
    )
    output_contract = "逐题给出答案和解析" if include_explanations else "逐题只给出答案，不要解析"
    grounded, _ = await GroundedAnswerGenerator(
        llm,
        min_similarity_score=0.0,
    ).answer(
        question=(
            f"{output_contract}。必须沿用原题号，回答下面这份已经生成的试卷；"
            "不得另出新题，也不得修改题目。\n\n"
            f"<previous_exam>\n{previous.content}\n</previous_exam>"
        ),
        standalone_question=(f"为紧邻上一份试卷{output_contract}，保持原题号和题目不变。"),
        hits=hits,
        style=AnswerStyle.DETAILED,
        model=model,
    )
    quality = previous_quality.model_copy(
        update={
            "answers_included": True,
            "explanations_included": include_explanations,
        }
    )
    plan_read = previous_plan.model_copy(
        update={
            "include_answers": True,
            "include_explanations": include_explanations,
        }
    )
    retrieval = previous_retrieval.model_copy(
        update={
            "retrieval_mode": "exam_legacy_context_answer",
            "original_question": question,
            "rewritten_query": question,
            "context_message_count": context_message_count,
            "rewrite_applied": False,
            "answer_scope": AnswerScope.COURSE_ONLY,
            "task_type": CourseTaskType.EXAM,
            "router_reason": (
                "检测到对旧版试卷的答案/解析续写请求；已使用原试卷文本和"
                "当时保存的课程证据回答，未重新出题。"
            ),
            "exam_plan": plan_read,
            "exam_quality": quality,
        }
    )
    selected_citations = [
        course_citations[source_id - 1]
        for source_id in grounded.used_source_ids
        if 1 <= source_id <= len(course_citations)
    ]
    usage = (
        AnswerTokenUsageRead(
            prompt_tokens=grounded.usage.prompt_tokens,
            completion_tokens=grounded.usage.completion_tokens,
            total_tokens=grounded.usage.total_tokens,
        )
        if grounded.usage is not None
        else None
    )
    return _CourseAnswerWork(
        answer=grounded,
        citations=selected_citations,
        retrieval=retrieval,
        usage=usage,
        elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
        task_type=CourseTaskType.EXAM,
        effective_scope=AnswerScope.COURSE_ONLY,
    )


async def _retrieve_summary_sections(
    *,
    course_id: UUID,
    plan: SummaryPlan,
    indexing: DocumentIndexingManager,
    candidate_k: int,
    configured_top_k: int,
    max_sources: int,
    max_context_chars: int,
    document_ids: list[str],
) -> tuple[RerankedRetrievalResult, dict[str, tuple[int, ...]]]:
    """Run one qualified retrieval per planned section and unify citation IDs."""

    section_results: list[tuple[str, RerankedRetrievalResult]] = []
    queries: list[str] = []
    dense_candidate_count = 0
    rejected_evidence_count = 0
    embedding_device: str | None = None
    reranker_device: str | None = None
    fallback_reasons: dict[str, None] = {}

    for section in plan.sections:
        query = summary_retrieval_query(
            f"{plan.scope_description} {section.retrieval_query}",
            plan.scope,
        )
        queries.append(f"{section.title}: {query}")
        result = await indexing.answer_search(
            course_id=course_id,
            query=query,
            candidate_k=candidate_k,
            top_k=min(configured_top_k, section.evidence_budget),
            document_ids=document_ids,
        )
        dense_candidate_count += result.dense_candidate_count
        rejected_evidence_count += result.rejected_evidence_count
        embedding_device = embedding_device or result.embedding_device
        reranker_device = reranker_device or result.reranker_device
        if result.fallback_reason:
            fallback_reasons.setdefault(result.fallback_reason, None)

        section_results.append((section.key, result))

    merged_hits: list[VectorSearchResult] = []
    source_id_by_point: dict[str, int] = {}
    mutable_section_source_ids: dict[str, list[int]] = {
        section.key: [] for section in plan.sections
    }
    total_context_chars = 0
    max_result_count = max(
        (len(result.hits) for _, result in section_results),
        default=0,
    )
    for rank in range(max_result_count):
        for section_key, result in section_results:
            if rank >= len(result.hits):
                continue
            hit = result.hits[rank]
            identity = hit.point_id or f"{hit.document_id}:{hit.chunk_index}"
            source_id = source_id_by_point.get(identity)
            if source_id is None:
                if len(merged_hits) >= max_sources:
                    continue
                remaining_chars = max_context_chars - total_context_chars
                if remaining_chars < 400:
                    continue
                if len(hit.text) > remaining_chars:
                    hit = replace(hit, text=hit.text[:remaining_chars])
                merged_hits.append(hit)
                total_context_chars += len(hit.text)
                source_id = len(merged_hits)
                source_id_by_point[identity] = source_id
            source_ids = mutable_section_source_ids[section_key]
            if source_id not in source_ids:
                source_ids.append(source_id)

    section_source_ids = {
        key: tuple(source_ids) for key, source_ids in mutable_section_source_ids.items()
    }

    return (
        RerankedRetrievalResult(
            query=" | ".join(queries),
            hits=tuple(merged_hits),
            dense_candidate_count=dense_candidate_count,
            rejected_evidence_count=rejected_evidence_count,
            embedding_device=embedding_device,
            reranker_device=reranker_device,
            fallback_reason=("；".join(fallback_reasons) if fallback_reasons else None),
        ),
        section_source_ids,
    )


def _bounded_exam_hits(
    hits: tuple[VectorSearchResult, ...],
    *,
    max_sources: int,
    max_context_chars: int,
) -> tuple[VectorSearchResult, ...]:
    bounded: list[VectorSearchResult] = []
    used_chars = 0
    for hit in hits[:max_sources]:
        remaining = max_context_chars - used_chars
        if remaining < 400:
            break
        if len(hit.text) > remaining:
            hit = replace(hit, text=hit.text[:remaining])
        bounded.append(hit)
        used_chars += len(hit.text)
    return tuple(bounded)


async def _persist_course_answer(
    *,
    course_id: UUID,
    conversation: Conversation,
    payload: CourseAnswerRequest,
    work: _CourseAnswerWork,
    service: ConversationService,
) -> CourseAnswerRead:
    retrieval_payload = work.retrieval.model_dump(mode="json")
    if work.exam_artifact is not None:
        # Private server-side continuation state. AnswerRetrievalRead ignores this
        # extra key, so neither answer responses nor conversation history expose it.
        retrieval_payload[_EXAM_ARTIFACT_KEY] = work.exam_artifact
    user_message, assistant_message = await service.record_exchange(
        conversation=conversation,
        question=payload.question,
        answer=work.answer.answer,
        answer_status=work.answer.status.value,
        answer_style=payload.answer_style.value,
        model=work.answer.model,
        citations=[citation.model_dump(mode="json") for citation in work.citations],
        retrieval=retrieval_payload,
        usage=work.usage.model_dump(mode="json") if work.usage is not None else None,
        elapsed_ms=work.elapsed_ms,
    )
    return CourseAnswerRead(
        agent_runtime=work.retrieval.agent_runtime,
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        course_id=course_id,
        question=payload.question,
        answer=work.answer.answer,
        status=work.answer.status,
        answer_style=payload.answer_style,
        answer_scope=work.effective_scope,
        model=work.answer.model,
        elapsed_ms=work.elapsed_ms,
        citations=work.citations,
        retrieval=work.retrieval,
        usage=work.usage,
        external_search=work.retrieval.external_search,
        task_type=work.task_type,
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


def _sanitize_quick_external_citations(
    content: str,
    *,
    available_count: int,
) -> tuple[str, tuple[int, ...]]:
    """Remove hallucinated Web citation labels without blocking a quick-chat answer."""

    used_ids: dict[int, None] = {}

    def replace(match: re.Match[str]) -> str:
        source_id = int(match.group(1))
        if 1 <= source_id <= available_count:
            used_ids.setdefault(source_id, None)
            return match.group(0)
        return ""

    return _QUICK_EXTERNAL_CITATION.sub(replace, content).strip(), tuple(used_ids)


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
        source_type=CitationSourceType.COURSE,
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


def _external_citation_read(
    *,
    source_id: int,
    evidence: ExternalSearchEvidence,
) -> AnswerCitationRead:
    return AnswerCitationRead(
        source_id=source_id,
        source_type=CitationSourceType.EXTERNAL,
        text=evidence.evidence_excerpt,
        title=evidence.title,
        publisher=evidence.publisher,
        url=evidence.url,
        accessed_at=evidence.accessed_at,
        content_role="external_evidence",
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, (int, str)):
        return int(value)
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, (float, int, str)):
        return float(value)
    return None
