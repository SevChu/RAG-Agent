from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.session import create_database_engine
from app.external_search import (
    ExternalSearchEvidence,
    ExternalSearchResult,
    ExternalSearchStatus,
    ExternalSourceQuality,
    get_external_search_gateway,
)
from app.generation import ChatCompletion, TokenUsage, get_chat_completion_gateway
from app.indexing import get_indexing_manager
from app.knowledge import VectorSearchResult
from app.main import app
from app.models import Document, DocumentStatus
from app.retrieval import RerankedRetrievalResult


async def _create_ready_document(
    client: AsyncClient,
    settings: Settings,
) -> tuple[str, str]:
    course_response = await client.post("/api/courses", json={"name": "数据结构"})
    course_id = str(course_response.json()["data"]["id"])
    upload_response = await client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("讲义.md", "# 栈\n\n后进先出".encode(), "text/markdown")},
    )
    document_id = str(upload_response.json()["data"]["id"])
    engine = create_database_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        document = await session.get(Document, UUID(document_id))
        assert document is not None
        document.status = DocumentStatus.COMPLETED
        await session.commit()
    await engine.dispose()
    return course_id, document_id


class FakeManager:
    def __init__(
        self,
        *,
        course_id: str,
        document_id: str,
        hits: bool = True,
        score: float = 0.91,
        unique_per_call: bool = False,
        text_size: int | None = None,
    ) -> None:
        self.course_id = course_id
        self.document_id = document_id
        self.hits = hits
        self.score = score
        self.unique_per_call = unique_per_call
        self.text_size = text_size
        self.calls: list[dict[str, object]] = []

    async def answer_search(
        self,
        *,
        course_id: UUID,
        query: str,
        candidate_k: int,
        top_k: int,
        document_ids: list[str],
    ) -> RerankedRetrievalResult:
        self.calls.append(
            {
                "course_id": course_id,
                "query": query,
                "candidate_k": candidate_k,
                "top_k": top_k,
                "document_ids": document_ids,
            }
        )
        results = (
            (
                VectorSearchResult(
                    point_id=(
                        f"point-{len(self.calls)}"
                        if self.unique_per_call
                        else "point-1"
                    ),
                    score=self.score,
                    course_id=self.course_id,
                    document_id=self.document_id,
                    chunk_index=3 + len(self.calls) if self.unique_per_call else 4,
                    text=(
                        "栈的插入与删除只能在线性表的一端进行，遵循后进先出。"
                        if self.text_size is None
                        else "课程证据" * self.text_size
                    ),
                    payload={
                        "file_name": "讲义.md",
                        "file_type": "md",
                        "section_path": ["栈", "基本概念"],
                        "page_numbers": [],
                        "slide_numbers": [],
                        "line_start": 8,
                        "line_end": 12,
                        "block_kinds": ["paragraph"],
                    },
                ),
            )
            if self.hits
            else ()
        )
        return RerankedRetrievalResult(
            query=query,
            hits=results,
            dense_candidate_count=len(results),
            rejected_evidence_count=0,
            embedding_device="cpu",
            reranker_device="cpu",
        )

    async def exam_search(
        self,
        *,
        course_id: UUID,
        query: str,
        candidate_k: int,
        top_k: int,
        document_ids: list[str],
    ) -> RerankedRetrievalResult:
        return await self.answer_search(
            course_id=course_id,
            query=query,
            candidate_k=candidate_k,
            top_k=top_k,
            document_ids=document_ids,
        )


class FakeGateway:
    def __init__(self) -> None:
        self.calls = 0
        self.models: list[str] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        self.calls += 1
        self.models.append(model)
        assert "## 结论" in system_prompt
        assert "## 关键要点" in system_prompt
        assert "后进先出" in user_prompt
        assert model in {"deepseek-v4-flash", "deepseek-v4-pro"}
        return ChatCompletion(
            content=(
                '{"sufficient_evidence":true,'
                '"answer":"栈只在一端插入和删除，并遵循后进先出原则。[1]",'
                '"used_source_ids":[1]}'
            ),
            model="deepseek-test",
            usage=TokenUsage(prompt_tokens=80, completion_tokens=16, total_tokens=96),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("course answer must not use plain text completion")


class ExamApiGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        self.calls += 1
        if "审查器" in system_prompt:
            return ChatCompletion(
                content=(
                    '{"results":[{"number":1,"supported":true,'
                    '"unsupported_claim":null}]}'
                ),
                model=model,
            )
        assert "试卷生成器" in system_prompt
        assert "number=1" in user_prompt
        return ChatCompletion(
            content=json.dumps(
                {
                    "questions": [
                        {
                            "number": 1,
                            "question_type": "true_false",
                            "difficulty": "easy",
                            "knowledge_point": "栈的操作端点",
                            "prompt": "判断：栈的插入和删除都在栈顶完成。",
                            "options": [],
                            "answer": "正确",
                            "explanation": "栈只允许在栈顶进行插入和删除。",
                            "source_mode": "course_generated",
                            "course_source_ids": [1],
                            "external_source_ids": [],
                            "input_description": None,
                            "output_description": None,
                            "constraints": [],
                            "samples": [],
                            "reference_code": None,
                            "complexity_analysis": None,
                            "test_case_design": [],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            model=model,
            usage=TokenUsage(prompt_tokens=90, completion_tokens=40, total_tokens=130),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("exam generation must use JSON completion")


class ContextGateway:
    def __init__(self) -> None:
        self.rewrite_prompts: list[str] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        if "检索查询改写器" in system_prompt:
            self.rewrite_prompts.append(user_prompt)
            return ChatCompletion(
                content=(
                    '{"standalone_query":"栈的后进先出特性有什么作用？"}'
                ),
                model=model,
            )
        return ChatCompletion(
            content=(
                '{"sufficient_evidence":true,'
                '"answer":"栈遵循后进先出原则。[1]",'
                '"used_source_ids":[1]}'
            ),
            model=model,
            usage=TokenUsage(prompt_tokens=50, completion_tokens=12, total_tokens=62),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("not used")


class FakeExternalSearch:
    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.calls: list[tuple[str, str]] = []

    async def search(self, *, query: str, model: str) -> ExternalSearchResult:
        self.calls.append((query, model))
        results = (
            ExternalSearchEvidence(
                rank=1,
                title="Python 3.14 documentation",
                publisher="Python Software Foundation",
                url="https://docs.python.org/3.14/",
                accessed_at=datetime(2026, 8, 4, tzinfo=UTC),
                evidence_excerpt="Python 3.14 官方文档描述了当前版本行为。",
                quality=ExternalSourceQuality.OFFICIAL,
            ),
        ) if self.succeed else ()
        return ExternalSearchResult(
            query=query,
            status=(
                ExternalSearchStatus.SUCCEEDED
                if self.succeed
                else ExternalSearchStatus.FAILED
            ),
            results=results,
            raw_result_count=len(results),
            provider="test",
            model=model,
            elapsed_ms=1.0,
            failure_reason=None if self.succeed else "外部检索服务返回 HTTP 503。",
        )


class MixedGateway:
    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        assert "[课n]" in system_prompt
        assert "[外n]" in system_prompt
        assert "docs.python.org" in user_prompt
        return ChatCompletion(
            content=(
                '{"sufficient_evidence":true,'
                '"answer":"课程给出栈的定义。[课1] 外部官方文档提供当前补充。[外1]",'
                '"used_course_source_ids":[1],"used_external_source_ids":[1],'
                '"has_source_conflict":false}'
            ),
            model="deepseek-test",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=30, total_tokens=130),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("not used")


class SummaryGateway:
    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        assert "逐节执行 <summary_plan>" in system_prompt
        assert '"is_default": true' in user_prompt
        return ChatCompletion(
            content=json.dumps(
                {
                    "sufficient_evidence": True,
                    "title": "数据结构课程总结",
                    "sections": [
                        {
                            "key": key,
                            "title": title,
                            "purpose": purpose,
                            "body": body,
                            "used_source_ids": [1],
                            "limitation": None,
                        }
                        for key, title, purpose, body in (
                            (
                                "core_framework",
                                "核心框架",
                                "建立概念骨架",
                                "课程资料以栈为核心示例。[课1]",
                            ),
                            (
                                "key_mechanisms",
                                "关键机制与要点",
                                "说明关键规则",
                                "栈在同一端完成插入与删除。[课1]",
                            ),
                            (
                                "connections",
                                "知识联系",
                                "梳理概念联系",
                                "栈顶把插入、删除操作与后进先出顺序联系起来。[课1]",
                            ),
                            (
                                "boundaries",
                                "边界与易错点",
                                "归纳边界和误区",
                                "不能把栈的后进先出误写成先进先出。[课1]",
                            ),
                            (
                                "review_priorities",
                                "复习重点",
                                "给出复习优先级",
                                "应优先掌握后进先出及栈顶操作约束。[课1]",
                            ),
                        )
                    ],
                    "review_advice": None,
                    "used_source_ids": [1],
                },
                ensure_ascii=False,
            ),
            model=model,
            usage=TokenUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("not used")


class ExplicitSummaryGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        self.calls += 1
        if "课程总结规划器" in system_prompt:
            content = {
                "goal": "从 C++ 实现角度总结二叉树遍历",
                "focuses": ["函数结构", "边界条件"],
                "audience": "课程学习者",
                "detail_level": "适中",
                "length": "简洁",
                "output_format": "对比说明",
                "must_include": [],
                "must_exclude": [],
                "sections": [
                    {
                        "key": "function_structure",
                        "title": "C++ 遍历函数结构",
                        "purpose": "说明递归遍历的函数结构",
                        "retrieval_query": "二叉树 C++ 递归 遍历 函数结构",
                        "evidence_budget": 3,
                        "organization": "代码结构清单",
                        "required_points": ["函数结构"],
                    },
                    {
                        "key": "error_boundaries",
                        "title": "容易写错的边界条件汇总",
                        "purpose": "归纳实现中容易写错的边界条件",
                        "retrieval_query": "二叉树 遍历 空指针 递归 边界 错误",
                        "evidence_budget": 3,
                        "organization": "错误检查清单",
                        "required_points": ["边界条件"],
                    },
                ],
            }
        else:
            content = {
                "sufficient_evidence": True,
                "title": "二叉树遍历的 C++ 实现",
                "sections": [
                    {
                        "key": "function_structure",
                        "title": "C++ 遍历函数结构",
                        "purpose": "说明递归遍历的函数结构",
                        "body": "函数结构先检查结点，再按遍历次序递归访问子树。[课1]",
                        "used_source_ids": [1],
                        "limitation": None,
                    },
                    {
                        "key": "error_boundaries",
                        "title": "容易写错的边界条件汇总",
                        "purpose": "归纳实现中容易写错的边界条件",
                        "body": "边界条件首先处理空结点，避免继续递归访问。[课1]",
                        "used_source_ids": [2],
                        "limitation": None,
                    },
                ],
                "review_advice": None,
                "used_source_ids": [1],
            }
        return ChatCompletion(
            content=json.dumps(content, ensure_ascii=False),
            model=model,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=60, total_tokens=160),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("not used")


async def test_answer_api_returns_verified_citation(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    manager = FakeManager(course_id=course_id, document_id=document_id)
    gateway = FakeGateway()
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "什么是栈？", "answer_style": "balanced"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "answered"
    assert data["answer"].endswith("[课1]")
    assert data["answer_scope"] == "course_and_external"
    assert data["external_search"]["status"] == "not_requested"
    assert data["model"] == "deepseek-test"
    assert data["conversation_id"]
    assert data["user_message_id"]
    assert data["assistant_message_id"]
    assert data["citations"][0]["source_id"] == 1
    assert data["citations"][0]["source_type"] == "course"
    assert data["citations"][0]["file_name"] == "讲义.md"
    assert data["citations"][0]["line_start"] == 8
    assert data["citations"][0]["content_role"] == "unknown"
    assert data["usage"]["total_tokens"] == 96
    assert data["retrieval"]["requested_top_k"] == 6
    assert data["retrieval"]["candidate_top_k"] == 20
    assert data["retrieval"]["retrieval_mode"] == "dense_rerank"
    assert data["retrieval"]["reranker_device"] == "cpu"
    assert data["retrieval"]["answer_scope"] == "course_and_external"
    assert manager.calls[0]["candidate_k"] == 20
    assert manager.calls[0]["document_ids"] == [document_id]
    assert gateway.calls == 1

    conversation_response = await api_client.get(
        f"/api/courses/{course_id}/conversations/{data['conversation_id']}"
    )
    assert conversation_response.status_code == 200
    conversation = conversation_response.json()["data"]
    assert conversation["title"] == "什么是栈？"
    assert [message["role"] for message in conversation["messages"]] == [
        "user",
        "assistant",
    ]
    assert conversation["messages"][1]["citations"][0]["file_name"] == "讲义.md"


async def test_course_chat_routes_exam_and_persists_hard_limit_diagnostics(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    manager = FakeManager(course_id=course_id, document_id=document_id)
    gateway = ExamApiGateway()
    external = FakeExternalSearch()
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: external

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={
            "question": (
                "请根据第三章内容出一份仅含1道判断题的单元试卷，"
                "但不要答案和解析，仅课程资料。"
            ),
            "answer_scope": "course_and_external",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["task_type"] == "exam"
    assert data["answer_scope"] == "course_only"
    assert data["retrieval"]["retrieval_mode"] == "exam_dense_rerank"
    assert data["retrieval"]["exam_plan"]["question_count"] == 1
    assert data["retrieval"]["exam_plan"]["programming_language"] == "C++"
    assert data["retrieval"]["exam_plan"]["max_course_adapted_count"] == 0
    assert data["retrieval"]["exam_plan"]["max_external_count"] == 0
    assert data["retrieval"]["exam_quality"]["passed"] is True
    assert data["retrieval"]["exam_quality"]["generated_question_count"] == 1
    assert data["external_search"]["triggered"] is False
    assert external.calls == []
    assert gateway.calls == 2
    assert "# 课程试卷" in data["answer"]
    assert "[课1]" in data["answer"]
    assert "**答案：**" not in data["answer"]
    assert "**解析：**" not in data["answer"]
    assert data["retrieval"]["exam_plan"]["include_answers"] is False
    assert data["retrieval"]["exam_plan"]["include_explanations"] is False

    conversation_response = await api_client.get(
        f"/api/courses/{course_id}/conversations/{data['conversation_id']}"
    )
    saved = conversation_response.json()["data"]["messages"][1]
    assert saved["retrieval"]["task_type"] == "exam"
    assert saved["retrieval"]["exam_quality"]["source_limits_passed"] is True


async def test_course_chat_routes_simulation_paper_with_answers_only(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    manager = FakeManager(course_id=course_id, document_id=document_id)
    gateway = ExamApiGateway()
    external = FakeExternalSearch()
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: external

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={
            "question": (
                "请根据第三章的内容出一份仅含1道判断题的模拟卷，"
                "但只要答案，暂时不用输出解析。"
            ),
            "answer_scope": "course_and_external",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["task_type"] == "exam"
    assert data["retrieval"]["exam_plan"]["question_count"] == 1
    assert data["retrieval"]["exam_plan"]["include_answers"] is True
    assert data["retrieval"]["exam_plan"]["include_explanations"] is False
    assert "# 课程试卷" in data["answer"]
    assert "**答案：** 正确" in data["answer"]
    assert "**解析：**" not in data["answer"]
    assert gateway.calls == 2


async def test_course_chat_summarizes_chapter_with_safe_cross_section_evidence(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    manager = FakeManager(
        course_id=course_id,
        document_id=document_id,
        score=0.02,
        unique_per_call=True,
        text_size=1000,
    )
    external = FakeExternalSearch()
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    app.dependency_overrides[get_chat_completion_gateway] = lambda: SummaryGateway()
    app.dependency_overrides[get_external_search_gateway] = lambda: external

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "总结第三章"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["task_type"] == "summary"
    assert data["answer_scope"] == "course_only"
    assert data["retrieval"]["task_type"] == "summary"
    assert data["retrieval"]["retrieval_mode"] == "summary_dense_rerank"
    assert data["retrieval"]["summary_scope"] == "topic"
    assert data["retrieval"]["requested_top_k"] == 12
    assert data["retrieval"]["summary_plan"]["is_default"] is True
    assert len(data["retrieval"]["summary_plan"]["sections"]) == 5
    assert data["retrieval"]["summary_quality"]["passed"] is True
    assert len(
        data["retrieval"]["summary_quality"]["cross_section_evidence_reuse"]
    ) == 4
    assert data["external_search"]["triggered"] is False
    assert external.calls == []
    assert "## 复习重点" in data["answer"]
    assert data["citations"][0]["source_type"] == "course"
    assert len(manager.calls) == 5
    assert data["retrieval"]["returned_count"] <= 2


async def test_explicit_summary_uses_dynamic_plan_and_section_queries(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    manager = FakeManager(course_id=course_id, document_id=document_id, score=0.02)
    external = FakeExternalSearch()
    gateway = ExplicitSummaryGateway()
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: external

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={
            "question": "从 C++ 实现角度总结二叉树遍历，重点说明函数结构和容易写错的边界。"
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    plan = data["retrieval"]["summary_plan"]
    assert plan["is_default"] is False
    assert plan["focuses"] == ["函数结构", "边界条件"]
    assert [section["title"] for section in plan["sections"]] == [
        "C++ 遍历函数结构",
        "容易写错的边界条件汇总",
    ]
    assert data["retrieval"]["summary_quality"]["passed"] is True
    assert data["retrieval"]["summary_quality"][
        "normalized_source_declarations"
    ] == ["error_boundaries"]
    assert len(manager.calls) == 2
    assert manager.calls[0]["query"] != manager.calls[1]["query"]
    assert gateway.calls == 2
    assert external.calls == []


async def test_answer_api_uses_selected_allowed_model(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    manager = FakeManager(course_id=course_id, document_id=document_id)
    gateway = FakeGateway()
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "什么是栈？", "model": "deepseek-v4-pro"},
    )

    assert response.status_code == 200
    assert gateway.calls == 1
    assert gateway.models == ["deepseek-v4-pro"]


async def test_answer_api_rejects_model_outside_server_allowlist(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, _ = await _create_ready_document(api_client, api_settings)

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "什么是栈？", "model": "untrusted-model"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUT"


async def test_answer_api_refuses_without_hits_and_skips_llm(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    manager = FakeManager(course_id=course_id, document_id=document_id, hits=False)
    gateway = FakeGateway()
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "红黑树如何旋转？", "answer_style": "concise"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "insufficient_evidence"
    assert data["citations"] == []
    assert data["model"] is None
    assert gateway.calls == 0


async def test_answer_api_reports_missing_key_without_exposing_it(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    app.dependency_overrides[get_indexing_manager] = lambda: FakeManager(
        course_id=course_id,
        document_id=document_id,
    )

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "什么是栈？"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


async def test_llm_configuration_api_never_returns_key(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get("/api/llm/config")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["configured"] is False
    assert data["model"] == "deepseek-v4-flash"
    assert data["answer_styles"] == ["concise", "balanced", "detailed"]
    assert data["rag_context_max_messages"] == 6
    assert data["quick_chat_context_max_messages"] == 10
    assert data["external_search_enabled"] is True
    assert "api_key" not in data


async def test_course_only_scope_is_preserved_and_search_is_not_requested(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    external = FakeExternalSearch()
    app.dependency_overrides[get_indexing_manager] = lambda: FakeManager(
        course_id=course_id,
        document_id=document_id,
    )
    app.dependency_overrides[get_chat_completion_gateway] = lambda: FakeGateway()
    app.dependency_overrides[get_external_search_gateway] = lambda: external

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "什么是栈？", "answer_scope": "course_only"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer_scope"] == "course_only"
    assert data["external_search"] == {
        "triggered": False,
        "status": "not_requested",
        "query": None,
        "result_count": 0,
        "used_result_count": 0,
        "failure_reason": None,
        "decision_reason": "仅课程资料模式已关闭外部检索。",
        "fallback_applied": False,
    }
    assert external.calls == []


async def test_mixed_scope_searches_and_returns_verified_external_citation(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    external = FakeExternalSearch()
    app.dependency_overrides[get_indexing_manager] = lambda: FakeManager(
        course_id=course_id,
        document_id=document_id,
    )
    app.dependency_overrides[get_chat_completion_gateway] = lambda: MixedGateway()
    app.dependency_overrides[get_external_search_gateway] = lambda: external

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "请联网补充栈的当前官方资料。"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer"].endswith("[外1]")
    assert [item["source_type"] for item in data["citations"]] == [
        "course",
        "external",
    ]
    assert data["citations"][1]["url"] == "https://docs.python.org/3.14/"
    assert data["external_search"]["triggered"] is True
    assert data["external_search"]["status"] == "succeeded"
    assert data["external_search"]["used_result_count"] == 1
    assert data["external_search"]["fallback_applied"] is False
    assert external.calls == [
        ("请联网补充栈的当前官方资料。", "deepseek-v4-flash")
    ]


async def test_non_temporal_current_node_wording_does_not_force_web_search(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    external = FakeExternalSearch()
    app.dependency_overrides[get_indexing_manager] = lambda: FakeManager(
        course_id=course_id,
        document_id=document_id,
    )
    app.dependency_overrides[get_chat_completion_gateway] = lambda: FakeGateway()
    app.dependency_overrides[get_external_search_gateway] = lambda: external

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "当前栈顶元素有什么特点？"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["external_search"]["triggered"] is False
    assert external.calls == []


async def test_search_failure_falls_back_to_course_answer(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    external = FakeExternalSearch(succeed=False)
    app.dependency_overrides[get_indexing_manager] = lambda: FakeManager(
        course_id=course_id,
        document_id=document_id,
    )
    app.dependency_overrides[get_chat_completion_gateway] = lambda: FakeGateway()
    app.dependency_overrides[get_external_search_gateway] = lambda: external

    response = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "请搜索并解释什么是栈？"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "answered"
    assert data["answer"].endswith("[课1]")
    assert data["external_search"]["status"] == "failed"
    assert data["external_search"]["fallback_applied"] is True
    assert data["external_search"]["failure_reason"] == "外部检索服务返回 HTTP 503。"


async def test_course_stream_rewrites_follow_up_and_persists_only_complete_answer(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    manager = FakeManager(course_id=course_id, document_id=document_id)
    gateway = ContextGateway()
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway

    first = await api_client.post(
        f"/api/courses/{course_id}/answers",
        json={"question": "什么是栈？"},
    )
    conversation_id = first.json()["data"]["conversation_id"]

    response = await api_client.post(
        f"/api/courses/{course_id}/answers/stream",
        json={
            "question": "它有什么作用？",
            "conversation_id": conversation_id,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: start" in response.text
    assert "event: delta" in response.text
    assert "event: citations" in response.text
    assert "event: complete" in response.text
    assert manager.calls[-1]["query"] == "栈的后进先出特性有什么作用？"
    assert len(gateway.rewrite_prompts) == 1
    detail = (
        await api_client.get(
            f"/api/courses/{course_id}/conversations/{conversation_id}"
        )
    ).json()["data"]
    assert [message["role"] for message in detail["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    retrieval = detail["messages"][-1]["retrieval"]
    assert retrieval["original_question"] == "它有什么作用？"
    assert retrieval["rewritten_query"] == "栈的后进先出特性有什么作用？"
    assert retrieval["context_message_count"] == 2
    assert retrieval["rewrite_applied"] is True
