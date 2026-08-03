from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.session import create_database_engine
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
    def __init__(self, *, course_id: str, document_id: str, hits: bool = True) -> None:
        self.course_id = course_id
        self.document_id = document_id
        self.hits = hits
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
                    point_id="point-1",
                    score=0.91,
                    course_id=self.course_id,
                    document_id=self.document_id,
                    chunk_index=4,
                    text="栈的插入与删除只能在线性表的一端进行，遵循后进先出。",
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

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "answered"
    assert data["answer"].endswith("[1]")
    assert data["model"] == "deepseek-test"
    assert data["conversation_id"]
    assert data["user_message_id"]
    assert data["assistant_message_id"]
    assert data["citations"][0]["source_id"] == 1
    assert data["citations"][0]["file_name"] == "讲义.md"
    assert data["citations"][0]["line_start"] == 8
    assert data["citations"][0]["content_role"] == "unknown"
    assert data["usage"]["total_tokens"] == 96
    assert data["retrieval"]["requested_top_k"] == 6
    assert data["retrieval"]["candidate_top_k"] == 20
    assert data["retrieval"]["retrieval_mode"] == "dense_rerank"
    assert data["retrieval"]["reranker_device"] == "cpu"
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
    assert "api_key" not in data


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
