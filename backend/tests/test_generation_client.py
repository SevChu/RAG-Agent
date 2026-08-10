from __future__ import annotations

from typing import Any

import httpx
from pytest import MonkeyPatch

from app.core.config import Settings
from app.generation.client import OpenAICompatibleChatClient


class FakeHTTPClient:
    payloads: list[dict[str, Any]] = []
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
