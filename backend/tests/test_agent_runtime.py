from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.external_search import get_external_search_gateway
from app.generation import ChatCompletion, get_chat_completion_gateway
from app.indexing import get_indexing_manager
from app.main import app
from tests.test_qa_api import (
    ExamApiGateway,
    ExplicitSummaryGateway,
    FakeExternalSearch,
    FakeManager,
    _create_ready_document,
    _sse_event_data,
)


class RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def complete_text(self, **kwargs: str) -> ChatCompletion:
        self.calls.append(kwargs)
        return ChatCompletion(content="模拟回复", model=kwargs["model"] + "-actual")

    async def complete(self, **kwargs: str) -> ChatCompletion:
        self.calls.append(kwargs)
        if "检索查询改写器" in kwargs["system_prompt"]:
            return ChatCompletion(content='{"standalone_query":"栈的特性"}', model=kwargs["model"])
        return ChatCompletion(
            content='{"sufficient_evidence":true,"answer":"后进先出。[1]","used_source_ids":[1]}',
            model=kwargs["model"] + "-actual",
        )


@pytest.fixture(autouse=True)
def configured(api_settings: Settings) -> None:
    api_settings.llm_api_key = "fixture-never-send"
    api_settings.llm_available_models = "model-a,model-b"
    api_settings.llm_model = "model-a"
    api_settings.qwen_models = ""
    api_settings.kimi_models = ""
    api_settings.glm_models = ""


async def profile(client: AsyncClient, **config: Any) -> dict[str, Any]:
    response = await client.post(
        "/api/agent-profiles",
        json={
            "name": "测试智能体",
            "config": {
                "model": {"provider": "deepseek", "model": "model-a"},
                "system_prompt": "版本一提示",
                "tools": {"web_search": False},
                **config,
            },
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def quick(client: AsyncClient, pid: str) -> dict[str, Any]:
    response = await client.post("/api/quick-conversations", json={"agent_profile_id": pid})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def test_quick_pins_revision_and_records_runtime(api_client: AsyncClient) -> None:
    gateway, search = RecordingGateway(), FakeExternalSearch()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: search
    original = await profile(api_client, context={"quick_max_messages": 1})
    a = await quick(api_client, original["id"])
    cfg = deepcopy(original["current_revision"]["config"])
    cfg["system_prompt"] = "版本二提示"
    cfg["model"]["model"] = "model-b"
    response = await api_client.patch(
        f"/api/agent-profiles/{original['id']}",
        json={
            "expected_row_version": 1,
            "config": cfg,
        },
    )
    r2 = response.json()["data"]["current_revision"]
    b = await quick(api_client, original["id"])
    assert a["agent_profile_revision_id"] == original["current_revision"]["id"]
    assert b["agent_profile_revision_id"] == r2["id"]
    for conv, model, prompt in ((a, "model-a", "版本一提示"), (b, "model-b", "版本二提示")):
        response = await api_client.post(
            f"/api/quick-conversations/{conv['id']}/messages/stream",
            json={"message": "搜索今天最新消息", "web_search": True},
        )
        assert response.status_code == 200, response.text
        start = _sse_event_data(response.text, "start")
        done = _sse_event_data(response.text, "complete")
        assert start["model"] == model
        assert start["context_max_messages"] == 1
        assert start["web_search_enabled"] is False
        assert done["agent_runtime"]["revision_id"] == conv["agent_profile_revision_id"]
        assert done["agent_runtime"]["actual_models"] == [model + "-actual"]
        assert prompt in gateway.calls[-1]["system_prompt"]
        assert "不检索课程资料" in gateway.calls[-1]["system_prompt"]
        history = (await api_client.get(f"/api/quick-conversations/{conv['id']}")).json()["data"]
        assert history["messages"][-1]["retrieval"]["agent_runtime"] == done["agent_runtime"]
    assert search.calls == []


@pytest.mark.parametrize("stream", [False, True])
async def test_course_r1_r2_scope_history_and_model_conflict(
    api_client: AsyncClient,
    api_settings: Settings,
    stream: bool,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    gateway, search = RecordingGateway(), FakeExternalSearch()
    manager = FakeManager(course_id=course_id, document_id=document_id)
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: search
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    original = await profile(
        api_client,
        allowed_course_ids=[course_id],
        retrieval={"answer_top_k": 2, "answer_candidate_k": 3},
        context={"rag_max_messages": 1},
    )
    root = f"/api/courses/{course_id}"
    a = (
        await api_client.post(
            root + "/conversations",
            json={
                "agent_profile_id": original["id"],
            },
        )
    ).json()["data"]
    cfg = deepcopy(original["current_revision"]["config"])
    cfg["system_prompt"] = "版本二提示"
    cfg["model"]["model"] = "model-b"
    cfg["retrieval"]["answer_top_k"] = 3
    response = await api_client.patch(
        f"/api/agent-profiles/{original['id']}",
        json={
            "expected_row_version": 1,
            "config": cfg,
        },
    )
    r2 = response.json()["data"]["current_revision"]
    b = (
        await api_client.post(
            root + "/conversations",
            json={
                "agent_profile_id": original["id"],
            },
        )
    ).json()["data"]
    endpoint = root + "/answers" + ("/stream" if stream else "")
    for conv, revision, model, k in (
        (a, original["current_revision"], "model-a", 2),
        (b, r2, "model-b", 3),
    ):
        for iteration in range(2):
            result = await api_client.post(
                endpoint,
                json={
                    "conversation_id": conv["id"],
                    "question": "解释栈并搜索最新研究",
                    "document_ids": [document_id],
                },
            )
            assert result.status_code == 200, result.text
            data = _sse_event_data(result.text, "complete") if stream else result.json()["data"]
            assert data["agent_runtime"]["revision_id"] == revision["id"]
            assert data["agent_runtime"]["config_sha256"] == revision["config_sha256"]
            assert data["retrieval"]["context_message_count"] == iteration
            assert data["model"] == model + "-actual"
            assert manager.calls[-1]["top_k"] == k
            assert manager.calls[-1]["candidate_k"] == 3
            assert manager.calls[-1]["document_ids"] == [document_id]
            assert data["citations"][0]["document_id"] == document_id
            assert all(call["model"] == model for call in gateway.calls[-(iteration + 1) :])
        history = (await api_client.get(root + f"/conversations/{conv['id']}")).json()["data"]
        assert history["messages"][-1]["retrieval"]["agent_runtime"] == data["agent_runtime"]
    assert search.calls == []
    calls = len(gateway.calls)
    for override in ({"model": "model-b"}, {"agent_profile_id": original["id"]}):
        bad = await api_client.post(
            endpoint,
            json={
                "conversation_id": a["id"],
                "question": "越权",
                **override,
            },
        )
        assert bad.status_code == 400, bad.text
    other = (await api_client.post("/api/courses", json={"name": "隔离空间"})).json()["data"]["id"]
    bad = await api_client.post(
        f"/api/courses/{other}/conversations",
        json={
            "agent_profile_id": original["id"],
        },
    )
    assert bad.status_code == 400
    bad = await api_client.post(
        f"/api/courses/{other}/answers",
        json={
            "conversation_id": a["id"],
            "question": "越权",
        },
    )
    assert bad.status_code == 404
    assert len(gateway.calls) == calls


class TracedGateway:
    def __init__(self, inner: Any, *, fail_first: bool = False) -> None:
        self.inner = inner
        self.fail_first = fail_first
        self.calls: list[dict[str, str]] = []

    async def complete(self, **kwargs: str) -> ChatCompletion:
        self.calls.append(kwargs)
        if self.fail_first and len(self.calls) == 1:
            return ChatCompletion(content="invalid-json", model=kwargs["model"])
        return await self.inner.complete(**kwargs)

    async def complete_text(self, **kwargs: str) -> ChatCompletion:
        raise AssertionError("summary/exam must use JSON")


@pytest.mark.parametrize("task", ["summary", "exam"])
@pytest.mark.parametrize("stream", [False, True])
async def test_planning_generation_repair_use_bound_model_and_limits(
    api_client: AsyncClient,
    api_settings: Settings,
    task: str,
    stream: bool,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    gateway = TracedGateway(
        ExplicitSummaryGateway() if task == "summary" else ExamApiGateway(),
        fail_first=task == "exam",
    )
    manager = FakeManager(course_id=course_id, document_id=document_id)
    search = FakeExternalSearch()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: search
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    original = await profile(
        api_client,
        allowed_course_ids=[course_id],
        tools={"web_search": task == "summary"},
        retrieval={
            f"{task}_top_k": 2,
            f"{task}_candidate_k": 3,
            f"{task}_max_sources": 2,
            f"{task}_context_max_chars": 2000,
        },
    )
    question = (
        "从 C++ 实现角度总结二叉树遍历，重点说明函数结构和容易写错的边界。"
        if task == "summary"
        else "出一份仅含1道判断题的试卷，联网补充，附答案"
    )
    result = await api_client.post(
        f"/api/courses/{course_id}/answers" + ("/stream" if stream else ""),
        json={"question": question, "agent_profile_id": original["id"]},
    )
    assert result.status_code == 200, result.text
    data = _sse_event_data(result.text, "complete") if stream else result.json()["data"]
    assert data["task_type"] == task
    assert data["answer_scope"] == "course_only"
    assert data["agent_runtime"]["requested_model"] == "model-a"
    assert data["agent_runtime"]["actual_models"] == ["model-a"]
    assert data["retrieval"][f"{task}_quality"]["passed"] is True
    assert len(gateway.calls) >= (2 if task == "summary" else 3)
    for call in gateway.calls:
        assert call["model"] == "model-a"
        assert "版本一提示" in call["system_prompt"]
        assert "服务端任务约束" in call["system_prompt"]
    assert all(call["top_k"] <= 2 and call["candidate_k"] == 3 for call in manager.calls)
    assert search.calls == []


@pytest.mark.parametrize("failure", ["disabled", "model", "key", "ambiguous", "deleted_course"])
async def test_invalid_runtime_blocks_before_sse_and_keeps_history(
    api_client: AsyncClient,
    api_settings: Settings,
    failure: str,
) -> None:
    course_id, _ = await _create_ready_document(api_client, api_settings)
    original = await profile(api_client, allowed_course_ids=[course_id])
    conv = await quick(api_client, original["id"])
    gateway = RecordingGateway()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    if failure == "disabled":
        await api_client.patch(
            f"/api/agent-profiles/{original['id']}",
            json={
                "expected_row_version": 1,
                "enabled": False,
            },
        )
    elif failure == "model":
        api_settings.llm_available_models = "model-b"
        api_settings.llm_model = "model-b"
    elif failure == "key":
        api_settings.llm_api_key = ""
    elif failure == "ambiguous":
        api_settings.qwen_models = "model-a"
        api_settings.qwen_api_key = "fixture"
    else:
        response = await api_client.delete(f"/api/courses/{course_id}")
        assert response.status_code == 200
    response = await api_client.post(
        f"/api/quick-conversations/{conv['id']}/messages/stream",
        json={"message": "继续", "web_search": False},
    )
    assert response.status_code in {400, 409, 503}, response.text
    assert "event: start" not in response.text
    assert gateway.calls == []
    new = await api_client.post(
        "/api/quick-conversations", json={"agent_profile_id": original["id"]}
    )
    assert new.status_code in {400, 409, 503}, new.text
    history = await api_client.get(f"/api/quick-conversations/{conv['id']}")
    assert history.status_code == 200
    assert history.json()["data"]["messages"] == []
    if failure == "disabled":
        await api_client.patch(
            f"/api/agent-profiles/{original['id']}",
            json={
                "expected_row_version": 2,
                "enabled": True,
            },
        )
        result = await api_client.post(
            f"/api/quick-conversations/{conv['id']}/messages/stream",
            json={"message": "恢复", "web_search": False},
        )
        assert _sse_event_data(result.text, "complete")["agent_runtime"]["revision_number"] == 1


@pytest.mark.parametrize(
    "server_enabled,profile_enabled,requested",
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
        (True, True, True),
    ],
)
async def test_quick_web_permission_intersection_and_no_course_retrieval(
    api_client: AsyncClient,
    api_settings: Settings,
    server_enabled: bool,
    profile_enabled: bool,
    requested: bool,
) -> None:
    api_settings.external_search_enabled = server_enabled
    original = await profile(api_client, tools={"web_search": profile_enabled})
    conv = await quick(api_client, original["id"])
    gateway, search = RecordingGateway(), FakeExternalSearch()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: search

    # A quick conversation must never require the course indexing dependency.
    def no_indexing() -> None:
        raise AssertionError("quick chat must not access course indexing")

    app.dependency_overrides[get_indexing_manager] = no_indexing
    response = await api_client.post(
        f"/api/quick-conversations/{conv['id']}/messages/stream",
        json={"message": "搜索今天最新消息", "web_search": requested},
    )
    done = _sse_event_data(response.text, "complete")
    assert done["external_search"]["triggered"] == (
        server_enabled and profile_enabled and requested
    )
    assert bool(search.calls) == (server_enabled and profile_enabled and requested)
    assert gateway.calls[0]["model"] == "model-a"


async def test_server_caps_and_old_conversation_isolation(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    gateway = RecordingGateway()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    legacy = (await api_client.post("/api/quick-conversations", json={})).json()["data"]
    original = await profile(
        api_client, context={"quick_max_messages": 30, "quick_max_chars": 40000}
    )
    conv = await quick(api_client, original["id"])
    api_settings.quick_chat_context_max_messages = 1
    api_settings.quick_chat_context_max_chars = 500
    for message in ("独有历史" * 200, "继续"):
        result = await api_client.post(
            f"/api/quick-conversations/{conv['id']}/messages/stream",
            json={"message": message, "web_search": False},
        )
        assert _sse_event_data(result.text, "start")["context_max_messages"] == 1
    assert "独有历史" not in gateway.calls[-1]["user_prompt"]  # Only the latest assistant remains.
    result = await api_client.post(
        f"/api/quick-conversations/{legacy['id']}/messages/stream",
        json={"message": "旧会话", "model": "model-b", "web_search": False},
    )
    done = _sse_event_data(result.text, "complete")
    assert done["agent_runtime"] is None
    assert done["context_message_count"] == 0
    assert gateway.calls[-1]["model"] == "model-b"
    assert "版本一提示" not in gateway.calls[-1]["system_prompt"]
    assert api_settings.quick_chat_context_max_messages == 1


async def test_exam_replay_remains_bound_and_cannot_expand_document_scope(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    gateway = TracedGateway(ExamApiGateway())
    manager = FakeManager(course_id=course_id, document_id=document_id)
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    original = await profile(api_client, allowed_course_ids=[course_id])
    root = f"/api/courses/{course_id}"
    response = await api_client.post(
        root + "/answers",
        json={
            "agent_profile_id": original["id"],
            "question": "出一份仅含1道判断题的试卷，不要答案和解析",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert "**答案：**" not in data["answer"]
    calls, searches = len(gateway.calls), len(manager.calls)
    response = await api_client.post(
        root + "/answers",
        json={
            "conversation_id": data["conversation_id"],
            "question": "补充答案和解析",
            "document_ids": [],
        },
    )
    assert response.status_code == 400, response.text
    response = await api_client.post(
        root + "/answers/stream",
        json={
            "conversation_id": data["conversation_id"],
            "question": "补充答案和解析",
            "document_ids": [document_id],
        },
    )
    done = _sse_event_data(response.text, "complete")
    assert "**答案：**" in done["answer"]
    assert done["agent_runtime"]["revision_id"] == original["current_revision"]["id"]
    assert done["agent_runtime"]["actual_models"] == []
    assert done["retrieval"]["retrieval_mode"] == "exam_artifact_replay"
    assert len(gateway.calls) == calls
    assert len(manager.calls) == searches
    assert "_exam_artifact" not in response.text


@pytest.mark.parametrize("stream", [False, True])
async def test_similarity_floor_and_refusal_without_generation(
    api_client: AsyncClient,
    api_settings: Settings,
    stream: bool,
) -> None:
    course_id, document_id = await _create_ready_document(api_client, api_settings)
    gateway, search = RecordingGateway(), FakeExternalSearch()
    manager = FakeManager(course_id=course_id, document_id=document_id, score=0.5)
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: search
    app.dependency_overrides[get_indexing_manager] = lambda: manager
    original = await profile(
        api_client,
        allowed_course_ids=[course_id],
        tools={"web_search": True},
        retrieval={"min_similarity_score": -1, "answer_top_k": 20, "answer_candidate_k": 100},
    )
    # Live server caps win even when the saved snapshot asks for more.
    api_settings.rag_min_similarity_score = 0.9
    api_settings.rag_answer_candidate_k = 2
    api_settings.rag_answer_top_k = 6
    response = await api_client.post(
        f"/api/courses/{course_id}/answers" + ("/stream" if stream else ""),
        json={
            "question": "什么是栈",
            "agent_profile_id": original["id"],
            "answer_scope": "course_only",
        },
    )
    assert response.status_code == 200, response.text
    done = _sse_event_data(response.text, "complete") if stream else response.json()["data"]
    assert done["status"] == "insufficient_evidence"
    assert done["agent_runtime"]["actual_models"] == []
    assert manager.calls[0]["top_k"] == manager.calls[0]["candidate_k"] == 2
    assert gateway.calls == search.calls == []
    assert api_settings.rag_answer_top_k == 6


async def test_failed_stream_has_no_completed_exchange(api_client: AsyncClient) -> None:
    from app.core.exceptions import LLMServiceError

    class BrokenGateway(RecordingGateway):
        async def complete_text(self, **kwargs: str) -> ChatCompletion:
            raise LLMServiceError("模拟失败")

    app.dependency_overrides[get_chat_completion_gateway] = lambda: BrokenGateway()
    original = await profile(api_client)
    conv = await quick(api_client, original["id"])
    response = await api_client.post(
        f"/api/quick-conversations/{conv['id']}/messages/stream",
        json={"message": "生成失败", "web_search": False},
    )
    assert _sse_event_data(response.text, "start")["agent_runtime"]["revision_number"] == 1
    assert _sse_event_data(response.text, "error")["code"] == "LLM_SERVICE_ERROR"
    assert "event: complete" not in response.text
    history = (await api_client.get(f"/api/quick-conversations/{conv['id']}")).json()["data"]
    assert history["messages"] == []


async def test_binding_input_rejects_overrides_and_empty_allowlist(api_client: AsyncClient) -> None:
    original = await profile(api_client)
    course = (await api_client.post("/api/courses", json={"name": "禁止访问"})).json()["data"]["id"]
    response = await api_client.post(
        f"/api/courses/{course}/answers",
        json={
            "question": "访问",
            "agent_profile_id": original["id"],
        },
    )
    assert response.status_code == 400
    assert (await api_client.get(f"/api/courses/{course}/conversations")).json()["data"] == []
    response = await api_client.post(
        "/api/quick-conversations",
        json={
            "agent_profile_id": original["id"],
            "agent_profile_revision_id": original["current_revision"]["id"],
        },
    )
    assert response.status_code == 422
    conv = await quick(api_client, original["id"])
    response = await api_client.post(
        f"/api/quick-conversations/{conv['id']}/messages/stream",
        json={
            "message": "切换",
            "agent_profile_id": original["id"],
        },
    )
    assert response.status_code == 422


async def test_offline_references_never_load_evaluators_at_runtime(
    api_client: AsyncClient,
    api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents import validation
    from tests.test_agent_profiles_api import evaluation_reference

    api_settings.agentic_edition = "research"
    original = await profile(api_client, evaluation_profiles=[evaluation_reference()])

    def unavailable() -> None:
        raise AssertionError("online runtime must not open the offline registry")

    monkeypatch.setattr(validation, "load_evaluation_catalog", unavailable)
    gateway = RecordingGateway()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    conv = await quick(api_client, original["id"])
    response = await api_client.post(
        f"/api/quick-conversations/{conv['id']}/messages/stream",
        json={
            "message": "继续",
            "web_search": False,
        },
    )
    assert _sse_event_data(response.text, "complete")["agent_runtime"]["revision_number"] == 1
    assert len(gateway.calls) == 1
