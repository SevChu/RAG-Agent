from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import Settings
from app.external_search import DeepSeekWebSearchAdapter


async def _run(query: str) -> int:
    settings = Settings()
    result = await DeepSeekWebSearchAdapter(settings).search(
        query=query,
        model=settings.llm_model,
    )
    print(f"status: {result.status.value}")
    print(f"provider/model: {result.provider}/{result.model}")
    print(f"raw/qualified: {result.raw_result_count}/{len(result.results)}")
    print(f"elapsed_ms: {result.elapsed_ms}")
    if result.failure_reason:
        print(f"reason: {result.failure_reason}")
    for item in result.results:
        print(f"\n[外{item.rank}] {item.title}")
        print(f"quality: {item.quality.value} | publisher: {item.publisher}")
        print(f"url: {item.url}")
        print(f"evidence: {item.evidence_excerpt}")
    return 0 if result.results else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Run one real DeepSeek Web Search request without exposing the API key."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="Python 3.14 官方发布文档与主要变化",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.query))


if __name__ == "__main__":
    raise SystemExit(main())
