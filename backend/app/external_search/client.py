from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import Depends
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings, get_settings
from app.external_search.models import (
    ExternalSearchEvidence,
    ExternalSearchResult,
    ExternalSearchStatus,
    ExternalSourceQuality,
)

_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_NAMES = {"fbclid", "gclid", "mc_cid", "mc_eid"}
_EXCLUDED_HOSTS = {
    "blog.csdn.net",
    "csdn.net",
    "facebook.com",
    "medium.com",
    "quora.com",
    "reddit.com",
    "weibo.com",
    "x.com",
    "zhihu.com",
}
_ACADEMIC_HOST_MARKERS = (
    "acm.org",
    "arxiv.org",
    "doi.org",
    "ieee.org",
    "jstor.org",
    "nature.com",
    "sciencedirect.com",
    "springer.com",
)
_INSTITUTIONAL_HOST_MARKERS = (
    "nist.gov",
    "nih.gov",
    "w3.org",
    "ietf.org",
    "iso.org",
)
_OFFICIAL_HOST_MARKERS = (
    "python.org",
    "docs.python.org",
    "developer.mozilla.org",
    "docs.github.com",
    "learn.microsoft.com",
    "kubernetes.io",
    "pytorch.org",
)


class ExternalSearchGateway(Protocol):
    async def search(self, *, query: str, model: str) -> ExternalSearchResult: ...


class _SummarySource(BaseModel):
    url: str = Field(min_length=1)
    publisher: str = ""
    evidence_excerpt: str = Field(min_length=1, max_length=600)


class _SummaryPayload(BaseModel):
    sources: list[_SummarySource] = Field(default_factory=list, max_length=20)


class DeepSeekWebSearchAdapter:
    """Use DeepSeek's Anthropic-compatible server-side Web Search tool."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def search(self, *, query: str, model: str) -> ExternalSearchResult:
        normalized_query = " ".join(query.split())
        started_at = perf_counter()
        if not normalized_query:
            return self._failed(
                query=normalized_query,
                model=model,
                started_at=started_at,
                reason="外部检索词不能为空。",
            )
        if not self.settings.external_search_enabled:
            return self._failed(
                query=normalized_query,
                model=model,
                started_at=started_at,
                reason="外部检索已由服务端配置关闭。",
            )
        api_key = self.settings.llm_api_key.strip()
        if not api_key:
            return self._failed(
                query=normalized_query,
                model=model,
                started_at=started_at,
                reason="尚未配置可用于外部检索的 API Key。",
            )

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": min(self.settings.llm_max_output_tokens, 1600),
            "thinking": {"type": "disabled"},
            "system": _search_system_prompt(self.settings.external_search_max_results),
            "messages": [{"role": "user", "content": normalized_query}],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": self.settings.external_search_max_uses,
                }
            ],
        }
        url = f"{self.settings.llm_base_url.rstrip('/')}/anthropic/v1/messages"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.external_search_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    url,
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException:
            return self._failed(
                query=normalized_query,
                model=model,
                started_at=started_at,
                reason="外部检索超时。",
            )
        except httpx.RequestError:
            return self._failed(
                query=normalized_query,
                model=model,
                started_at=started_at,
                reason="无法连接外部检索服务。",
            )

        if response.is_error:
            return self._failed(
                query=normalized_query,
                model=model,
                started_at=started_at,
                reason=f"外部检索服务返回 HTTP {response.status_code}。",
            )
        try:
            body = response.json()
        except ValueError:
            return self._failed(
                query=normalized_query,
                model=model,
                started_at=started_at,
                reason="外部检索服务返回了无法解析的响应。",
            )

        raw_results, tool_error = _raw_search_results(body)
        if tool_error is not None:
            return self._failed(
                query=normalized_query,
                model=model,
                started_at=started_at,
                reason=f"外部检索工具失败：{tool_error}。",
            )
        summaries = _summary_map(body)
        accessed_at = datetime.now(UTC)
        candidates: list[tuple[int, ExternalSearchEvidence]] = []
        seen_urls: set[str] = set()
        for raw_rank, item in enumerate(raw_results, start=1):
            raw_url = item.get("url")
            title = item.get("title")
            if not isinstance(raw_url, str) or not isinstance(title, str):
                continue
            clean_url = _clean_url(raw_url)
            canonical_url = _canonical_url(clean_url)
            host = _host(clean_url)
            if not canonical_url or not host or _is_excluded_host(host):
                continue
            if canonical_url in seen_urls:
                continue
            summary = summaries.get(_canonical_url(raw_url)) or summaries.get(canonical_url)
            if summary is None or not summary.evidence_excerpt.strip():
                continue
            seen_urls.add(canonical_url)
            quality = _source_quality(host)
            candidates.append(
                (
                    raw_rank,
                    ExternalSearchEvidence(
                        rank=raw_rank,
                        title=" ".join(title.split()),
                        publisher=summary.publisher.strip() or _publisher_from_host(host),
                        url=clean_url,
                        accessed_at=accessed_at,
                        evidence_excerpt=" ".join(summary.evidence_excerpt.split()),
                        quality=quality,
                        page_age=(
                            str(item["page_age"])
                            if item.get("page_age") is not None
                            else None
                        ),
                    ),
                )
            )

        candidates.sort(key=lambda pair: (_quality_order(pair[1].quality), pair[0]))
        limited = candidates[: self.settings.external_search_max_results]
        results = tuple(
            ExternalSearchEvidence(
                rank=rank,
                title=evidence.title,
                publisher=evidence.publisher,
                url=evidence.url,
                accessed_at=evidence.accessed_at,
                evidence_excerpt=evidence.evidence_excerpt,
                quality=evidence.quality,
                page_age=evidence.page_age,
            )
            for rank, (_, evidence) in enumerate(limited, start=1)
        )
        status = (
            ExternalSearchStatus.SUCCEEDED
            if results
            else ExternalSearchStatus.NO_QUALIFIED_RESULTS
        )
        failure_reason = None if results else "未取得可核验且质量合格的外部来源。"
        return ExternalSearchResult(
            query=normalized_query,
            status=status,
            results=results,
            raw_result_count=len(raw_results),
            provider=self.settings.llm_provider,
            model=str(body.get("model") or model),
            elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
            failure_reason=failure_reason,
        )

    def _failed(
        self,
        *,
        query: str,
        model: str,
        started_at: float,
        reason: str,
    ) -> ExternalSearchResult:
        return ExternalSearchResult(
            query=query,
            status=ExternalSearchStatus.FAILED,
            results=(),
            raw_result_count=0,
            provider=self.settings.llm_provider,
            model=model,
            elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
            failure_reason=reason,
        )


def _search_system_prompt(max_results: int) -> str:
    return f"""你是课程学习系统的外部证据检索器。必须调用一次 web_search。
优先选择论文、学术出版社、大学、科研机构、标准组织、政府网站和官方技术文档；
论坛、自媒体、聚合搬运站和无作者 SEO 页面不得作为优先证据。

搜索完成后只能输出一个 JSON 对象，不要输出 Markdown：
{{"sources":[{{"url":"必须逐字复制搜索结果 URL","publisher":"发布机构或网站",
"evidence_excerpt":"与查询直接相关、可由该页面核验的简短证据摘要"}}]}}

要求：
1. 最多返回 {max_results * 2} 项，只能填写本次真实搜索结果中出现的 URL，禁止杜撰 URL。
2. evidence_excerpt 是不超过 300 字的忠实摘要，不得加入搜索内容未支持的事实。
3. 无合格来源时返回 {{"sources":[]}}。
"""


def _raw_search_results(body: object) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(body, Mapping):
        return [], "invalid_response"
    results: list[dict[str, Any]] = []
    for block in body.get("content", []):
        if not isinstance(block, Mapping) or block.get("type") != "web_search_tool_result":
            continue
        content = block.get("content")
        if isinstance(content, Mapping):
            return [], str(content.get("error_code") or "unknown_error")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "web_search_result":
                results.append(item)
    return results, None


def _summary_map(body: object) -> dict[str, _SummarySource]:
    if not isinstance(body, Mapping):
        return {}
    text_blocks = [
        str(block.get("text", ""))
        for block in body.get("content", [])
        if isinstance(block, Mapping) and block.get("type") == "text"
    ]
    for text in reversed(text_blocks):
        try:
            payload = _SummaryPayload.model_validate_json(_json_object(text))
        except (ValueError, ValidationError):
            continue
        return {
            _canonical_url(source.url): source
            for source in payload.sources
            if _canonical_url(source.url)
        }
    return {}


def _json_object(text: str) -> str:
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON object not found")
    candidate = stripped[start : end + 1]
    json.loads(candidate)
    return candidate


def _clean_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    query = urlencode(
        [
            (name, item)
            for name, item in parse_qsl(parsed.query, keep_blank_values=True)
            if name.lower() not in _TRACKING_QUERY_NAMES
            and not name.lower().startswith(_TRACKING_QUERY_PREFIXES)
        ]
    )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, query, ""))


def _canonical_url(value: str) -> str:
    clean = _clean_url(value)
    if not clean:
        return ""
    parsed = urlsplit(clean)
    return urlunsplit(("https", parsed.netloc, parsed.path.rstrip("/") or "/", parsed.query, ""))


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_excluded_host(host: str) -> bool:
    return any(host == item or host.endswith(f".{item}") for item in _EXCLUDED_HOSTS)


def _source_quality(host: str) -> ExternalSourceQuality:
    if any(marker in host for marker in _ACADEMIC_HOST_MARKERS):
        return ExternalSourceQuality.ACADEMIC
    if (
        host.endswith((".edu", ".edu.cn", ".ac.uk", ".gov", ".gov.cn"))
        or any(marker in host for marker in _INSTITUTIONAL_HOST_MARKERS)
    ):
        return ExternalSourceQuality.INSTITUTIONAL
    if host.startswith(("docs.", "developer.")) or any(
        marker in host for marker in _OFFICIAL_HOST_MARKERS
    ):
        return ExternalSourceQuality.OFFICIAL
    return ExternalSourceQuality.PROFESSIONAL


def _quality_order(quality: ExternalSourceQuality) -> int:
    return {
        ExternalSourceQuality.ACADEMIC: 0,
        ExternalSourceQuality.INSTITUTIONAL: 1,
        ExternalSourceQuality.OFFICIAL: 2,
        ExternalSourceQuality.PROFESSIONAL: 3,
    }[quality]


def _publisher_from_host(host: str) -> str:
    return host.removeprefix("www.")


def get_external_search_gateway(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ExternalSearchGateway:
    return DeepSeekWebSearchAdapter(settings)
