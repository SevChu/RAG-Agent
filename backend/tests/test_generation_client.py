from __future__ import annotations

from typing import Any

import httpx
from pytest import MonkeyPatch

from app.core.config import Settings
from app.generation.client import OpenAICompatibleChatClient


class FakeHTTPClient:
    payloads: list[dict[str, Any]] = []
    urls: list[str] = []
    headers: list[dict[str, str]] = []
    statuses: list[int] = [200]

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> FakeHTTPClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> httpx.Response:
        self.payloads.append(json)
        self.urls.append(url)
        self.headers.append(headers)
        status = self.statuses.pop(0)
        request = httpx.Request("POST", url, headers=headers)
        if status == 200:
            body: dict[str, object] = {
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "model": json["model"],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "prompt_cache_hit_tokens": 6,
                    "prompt_cache_miss_tokens": 4,
                },
            }
        else:
            body = {"error": {"message": "temporary unavailable"}}
        return httpx.Response(status, json=body, request=request)


def _client(monkeypatch: MonkeyPatch, *, statuses: list[int]) -> OpenAICompatibleChatClient:
    FakeHTTPClient.payloads = []
    FakeHTTPClient.urls = []
    FakeHTTPClient.headers = []
    FakeHTTPClient.statuses = list(statuses)
    monkeypatch.setattr("app.generation.client.httpx.AsyncClient", FakeHTTPClient)
    settings = Settings(
        _env_file=None,
        llm_api_key="test-key",
        llm_model="deepseek-v4-flash",
        llm_available_models="deepseek-v4-flash",
    )
    return OpenAICompatibleChatClient(settings)


async def test_json_mode_always_includes_lowercase_json_literal(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch, statuses=[200])

    completion = await client.complete(
        system_prompt="只能输出大写 JSON。",
        user_prompt="返回结构化结果。",
        model="deepseek-v4-flash",
    )

    system_content = FakeHTTPClient.payloads[0]["messages"][0]["content"]
    assert "json" in system_content
    assert FakeHTTPClient.payloads[0]["response_format"] == {"type": "json_object"}
    assert completion.content == '{"ok":true}'
    assert completion.usage is not None
    assert completion.usage.prompt_cache_hit_tokens == 6
    assert completion.usage.prompt_cache_miss_tokens == 4


async def test_json_client_retries_one_transient_upstream_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch, statuses=[503, 200])

    completion = await client.complete(
        system_prompt="Return json.",
        user_prompt="test",
        model="deepseek-v4-flash",
    )

    assert completion.content == '{"ok":true}'
    assert len(FakeHTTPClient.payloads) == 2


async def test_qwen_model_uses_its_own_endpoint_and_key_without_deepseek_parameters(
    monkeypatch: MonkeyPatch,
) -> None:
    FakeHTTPClient.payloads = []
    FakeHTTPClient.urls = []
    FakeHTTPClient.headers = []
    FakeHTTPClient.statuses = [200]
    monkeypatch.setattr("app.generation.client.httpx.AsyncClient", FakeHTTPClient)
    settings = Settings(
        _env_file=None,
        llm_api_key="deepseek-key",
        llm_available_models="deepseek-test",
        qwen_api_key="qwen-key",
        qwen_models="qwen-test",
        qwen_base_url="https://qwen.example/v1",
    )
    client = OpenAICompatibleChatClient(settings)

    completion = await client.complete_text(
        system_prompt="You are helpful.",
        user_prompt="test",
        model="qwen-test",
    )

    assert completion.model == "qwen-test"
    assert FakeHTTPClient.urls == ["https://qwen.example/v1/chat/completions"]
    assert FakeHTTPClient.headers[0]["Authorization"] == "Bearer qwen-key"
    assert "thinking" not in FakeHTTPClient.payloads[0]


def test_settings_reserve_all_providers_and_merge_model_allowlists() -> None:
    settings = Settings(
        _env_file=None,
        llm_available_models="deepseek-test",
        qwen_models="qwen-test",
        kimi_models="kimi-test",
        glm_models="glm-test",
    )

    assert [provider.id for provider in settings.llm_providers] == [
        "deepseek",
        "qwen",
        "kimi",
        "glm",
    ]
    assert settings.available_models == [
        "deepseek-test",
        "qwen-test",
        "kimi-test",
        "glm-test",
    ]
    kimi = settings.provider_for_model("kimi-test")
    assert kimi is not None
    assert kimi.api_key_env == "KIMI_API_KEY"
