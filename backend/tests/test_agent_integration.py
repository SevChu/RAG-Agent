"""Week 7 cross-layer checks; HTTP responses and disconnect signals are synthetic."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import httpx
import pytest
from starlette.requests import Request

from app.core.config import Settings
from app.external_search import get_external_search_gateway
from app.generation import get_chat_completion_gateway
from app.generation.client import OpenAICompatibleChatClient
from app.indexing import get_indexing_manager
from app.main import app
from tests.test_agent_runtime import RecordingGateway, profile, quick
from tests.test_qa_api import (
    FakeExternalSearch,
    FakeManager,
    _create_ready_document,
    _sse_event_data,
)


@pytest.fixture(autouse=True)
def configured(api_settings: Settings) -> None:
    api_settings.llm_api_key = "fixture-deepseek"
    api_settings.llm_available_models = "model-a"
    api_settings.llm_model = "model-a"
    api_settings.llm_base_url = "https://deepseek.example/v1"
    for provider in ("qwen", "kimi", "glm"):
        setattr(api_settings, f"{provider}_api_key", f"fixture-{provider}")
        setattr(api_settings, f"{provider}_models", f"{provider}-model")
        setattr(api_settings, f"{provider}_base_url", f"https://{provider}.example/v1")


@pytest.mark.parametrize("provider", ["deepseek", "qwen", "kimi", "glm"])
async def test_bound_provider_routes_real_client_without_extra_requests(
    api_client: httpx.AsyncClient,
    api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    import json

    selected = "model-a" if provider == "deepseek" else f"{provider}-model"
    original = await profile(api_client, model={"provider": provider, "model": selected})
    conv = await quick(api_client, original["id"])
    # New conversations switch provider, but this conversation must keep the old endpoint/key.
    config = deepcopy(original["current_revision"]["config"])
    replacement = "qwen" if provider == "deepseek" else "deepseek"
    config["model"] = {
        "provider": replacement,
        "model": "qwen-model" if replacement == "qwen" else "model-a",
    }
    patched = await api_client.patch(
        f"/api/agent-profiles/{original['id']}",
        json={"expected_row_version": 1, "config": config},
    )
    assert patched.status_code == 200
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "合成供应商响应"}}],
                "model": selected + "-actual",
            },
        )

    original_client = httpx.AsyncClient

    def isolated_client(**kwargs: Any) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr("app.generation.client.httpx.AsyncClient", isolated_client)
    gateway = OpenAICompatibleChatClient(api_settings)
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    response = await api_client.post(
        f"/api/quick-conversations/{conv['id']}/messages/stream",
        json={"message": "验证固定路由", "web_search": False},
    )
    assert response.status_code == 200
    done = _sse_event_data(response.text, "complete")
    assert done["agent_runtime"]["provider"] == provider
    assert done["agent_runtime"]["revision_number"] == 1
    assert done["agent_runtime"]["actual_models"] == [selected + "-actual"]
    assert len(requests) == 1
    assert str(requests[0].url) == f"https://{provider}.example/v1/chat/completions"
    assert requests[0].headers["Authorization"] == f"Bearer fixture-{provider}"
    payload = json.loads(requests[0].content)
    assert payload["model"] == selected
    assert ("thinking" in payload) is (provider == "deepseek")
    assert "fixture-" not in response.text


@pytest.mark.parametrize("kind", ["quick", "course"])
@pytest.mark.parametrize("disconnect_at", [1, 2])
async def test_disconnect_before_or_after_delta_preserves_binding_without_exchange(
    api_client: httpx.AsyncClient,
    api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    disconnect_at: int,
) -> None:
    gateway = RecordingGateway()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    app.dependency_overrides[get_external_search_gateway] = lambda: FakeExternalSearch()
    if kind == "quick":
        original = await profile(api_client)
        conv = await quick(api_client, original["id"])
        history_url = f"/api/quick-conversations/{conv['id']}"
        endpoint = history_url + "/messages/stream"
        payload = {"message": "中断测试", "web_search": False}
    else:
        course, document = await _create_ready_document(api_client, api_settings)
        manager = FakeManager(course_id=course, document_id=document)
        app.dependency_overrides[get_indexing_manager] = lambda: manager
        original = await profile(api_client, allowed_course_ids=[course])
        created = await api_client.post(
            f"/api/courses/{course}/conversations",
            json={"agent_profile_id": original["id"]},
        )
        assert created.status_code == 201
        conv = created.json()["data"]
        history_url = f"/api/courses/{course}/conversations/{conv['id']}"
        endpoint = f"/api/courses/{course}/answers/stream"
        payload = {"conversation_id": conv["id"], "question": "什么是栈"}
    checks = 0

    async def disconnected(self: Request) -> bool:
        nonlocal checks
        checks += 1
        return checks >= disconnect_at

    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    response = await api_client.post(endpoint, json=payload)
    assert response.status_code == 200
    assert "event: start" in response.text
    assert ("event: delta" in response.text) is (disconnect_at == 2)
    assert "event: complete" not in response.text
    assert len(gateway.calls) == 1
    history = (await api_client.get(history_url)).json()["data"]
    assert history["messages"] == []
    assert history["agent_profile_revision_id"] == original["current_revision"]["id"]
    # Restoring the transport permits retry on the same immutable revision.
    monkeypatch.undo()
    retry = await api_client.post(endpoint, json=payload)
    assert _sse_event_data(retry.text, "complete")["agent_runtime"]["revision_number"] == 1
    assert len((await api_client.get(history_url)).json()["data"]["messages"]) == 2
