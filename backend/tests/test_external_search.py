from __future__ import annotations

import json

import httpx

from app.core.config import Settings
from app.external_search import (
    DeepSeekWebSearchAdapter,
    ExternalSearchStatus,
    ExternalSourceQuality,
)


def _settings() -> Settings:
    return Settings(
        llm_api_key="test-key",
        external_search_max_results=4,
        external_search_max_uses=1,
    )


async def test_adapter_parses_real_contract_and_prioritizes_sources() -> None:
    raw_results = [
        {
            "type": "web_search_result",
            "title": "搬运文章",
            "url": "https://blog.csdn.net/example/article/details/1",
            "encrypted_content": "opaque",
            "page_age": "1 day ago",
        },
        {
            "type": "web_search_result",
            "title": "Python 3.14 documentation",
            "url": "https://docs.python.org/3.14/?utm_source=search",
            "encrypted_content": "opaque",
            "page_age": "2 days ago",
        },
        {
            "type": "web_search_result",
            "title": "A scheduling paper",
            "url": "https://dl.acm.org/doi/10.1145/example",
            "encrypted_content": "opaque",
            "page_age": None,
        },
    ]
    summary = {
        "sources": [
            {
                "url": raw_results[0]["url"],
                "publisher": "CSDN",
                "evidence_excerpt": "不应被接纳",
            },
            {
                "url": raw_results[1]["url"],
                "publisher": "Python Software Foundation",
                "evidence_excerpt": "官方文档列出 Python 3.14 的语言与库参考。",
            },
            {
                "url": raw_results[2]["url"],
                "publisher": "ACM",
                "evidence_excerpt": "论文讨论了调度算法的实验结果。",
            },
            {
                "url": "https://invented.example/source",
                "publisher": "Invented",
                "evidence_excerpt": "不在真实搜索结果中，必须丢弃。",
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/anthropic/v1/messages"
        assert request.headers["x-api-key"] == "test-key"
        payload = json.loads(request.content)
        assert payload["tools"][0]["type"] == "web_search_20250305"
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "usage": {
                    "input_tokens": 80,
                    "cache_creation_input_tokens": 40,
                    "cache_read_input_tokens": 20,
                    "output_tokens": 35,
                },
                "content": [
                    {
                        "type": "server_tool_use",
                        "id": "srv-1",
                        "name": "web_search",
                        "input": {"query": "Python 3.14"},
                    },
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "srv-1",
                        "content": raw_results,
                    },
                    {"type": "text", "text": json.dumps(summary, ensure_ascii=False)},
                ],
            },
        )

    adapter = DeepSeekWebSearchAdapter(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.search(query="  Python   3.14  ", model="deepseek-v4-flash")

    assert result.status is ExternalSearchStatus.SUCCEEDED
    assert result.query == "Python 3.14"
    assert result.raw_result_count == 3
    assert len(result.results) == 2
    assert result.results[0].quality is ExternalSourceQuality.ACADEMIC
    assert result.results[1].quality is ExternalSourceQuality.OFFICIAL
    assert result.results[1].url == "https://docs.python.org/3.14/"
    assert [item.rank for item in result.results] == [1, 2]
    assert result.usage is not None
    assert result.usage.input_cache_hit_tokens == 20
    assert result.usage.input_cache_miss_tokens == 120
    assert result.usage.total_tokens == 175


async def test_adapter_reports_tool_error_without_raising() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "content": [
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "srv-1",
                        "content": {
                            "type": "web_search_tool_result_error",
                            "error_code": "unavailable",
                        },
                    }
                ],
            },
        )

    adapter = DeepSeekWebSearchAdapter(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.search(query="test", model="deepseek-v4-flash")

    assert result.status is ExternalSearchStatus.FAILED
    assert result.results == ()
    assert result.failure_reason == "外部检索工具失败：unavailable。"


async def test_adapter_returns_no_qualified_results_when_summary_is_unverifiable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "content": [
                    {
                        "type": "web_search_tool_result",
                        "tool_use_id": "srv-1",
                        "content": [
                            {
                                "type": "web_search_result",
                                "title": "Real source",
                                "url": "https://example.edu/paper",
                                "encrypted_content": "opaque",
                            }
                        ],
                    },
                    {
                        "type": "text",
                        "text": '{"sources":[{"url":"https://invented.example",'
                        '"publisher":"x","evidence_excerpt":"not real"}]}',
                    },
                ],
            },
        )

    adapter = DeepSeekWebSearchAdapter(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.search(query="test", model="deepseek-v4-flash")

    assert result.status is ExternalSearchStatus.NO_QUALIFIED_RESULTS
    assert result.raw_result_count == 1
    assert result.results == ()


async def test_non_deepseek_generation_model_keeps_deepseek_search_routing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.host == "api.deepseek.com"
        assert request.headers["x-api-key"] == "deepseek-key"
        assert payload["model"] == "deepseek-search-model"
        return httpx.Response(
            200,
            json={
                "model": "deepseek-search-model",
                "content": [{"type": "text", "text": '{"sources":[]}'}],
            },
        )

    settings = Settings(
        _env_file=None,
        llm_api_key="deepseek-key",
        llm_available_models="deepseek-chat",
        qwen_api_key="qwen-key",
        qwen_models="qwen-chat",
        external_search_model="deepseek-search-model",
    )
    adapter = DeepSeekWebSearchAdapter(settings, transport=httpx.MockTransport(handler))

    result = await adapter.search(query="current information", model="qwen-chat")

    assert result.status is ExternalSearchStatus.NO_QUALIFIED_RESULTS
    assert result.model == "deepseek-search-model"