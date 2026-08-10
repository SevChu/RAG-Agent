from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.evaluation import (
    BudgetedChatCompletionGateway,
    BudgetedExternalSearchGateway,
    BudgetExceededError,
    TokenBudgetLedger,
)
from app.external_search import (
    ExternalSearchEvidence,
    ExternalSearchResult,
    ExternalSearchStatus,
    ExternalSearchTokenUsage,
    ExternalSourceQuality,
)
from app.generation import ChatCompletion, TokenUsage
from scripts.audit_week4_integration import _ordered_results, _previous_results


class _ChatGateway:
    async def complete(self, **_: str) -> ChatCompletion:
        return ChatCompletion(
            content="{}",
            model="test",
            usage=TokenUsage(prompt_tokens=8, completion_tokens=2, total_tokens=10),
        )

    async def complete_text(self, **kwargs: str) -> ChatCompletion:
        return await self.complete(**kwargs)


class _SearchGateway:
    async def search(self, *, query: str, model: str) -> ExternalSearchResult:
        return ExternalSearchResult(
            query=query,
            status=ExternalSearchStatus.SUCCEEDED,
            results=(
                ExternalSearchEvidence(
                    rank=1,
                    title="Source",
                    publisher="Publisher",
                    url="https://example.edu/source",
                    accessed_at=datetime(2026, 8, 10, tzinfo=UTC),
                    evidence_excerpt="Evidence",
                    quality=ExternalSourceQuality.ACADEMIC,
                ),
            ),
            raw_result_count=1,
            provider="test",
            model=model,
            elapsed_ms=1.0,
            usage=ExternalSearchTokenUsage(
                input_tokens=20,
                output_tokens=5,
                total_tokens=25,
            ),
        )


async def test_budgeted_chat_charges_before_call_and_persists_actual_usage(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger = TokenBudgetLedger(limit_tokens=20_000, path=ledger_path)
    gateway = BudgetedChatCompletionGateway(
        _ChatGateway(),
        ledger,
        max_output_tokens=100,
    )

    await gateway.complete(
        system_prompt="system",
        user_prompt="question",
        model="test",
    )

    snapshot = ledger.snapshot()
    assert snapshot.call_count == 1
    assert snapshot.reported_tokens == 10
    assert 0 < snapshot.accounted_tokens <= 20_000
    stored = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert stored["charges"][0]["status"] == "completed"


async def test_persisted_ledger_prevents_a_later_process_from_exceeding_limit(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.json"
    first = TokenBudgetLedger(limit_tokens=2_500, path=ledger_path)
    first.charge(label="first", maximum_tokens=2_000)
    resumed = TokenBudgetLedger(limit_tokens=2_500, path=ledger_path)

    with pytest.raises(BudgetExceededError):
        resumed.charge(label="second", maximum_tokens=501)


async def test_external_search_has_a_separate_conservative_reservation() -> None:
    ledger = TokenBudgetLedger(limit_tokens=150_000)
    gateway = BudgetedExternalSearchGateway(_SearchGateway(), ledger)

    result = await gateway.search(query="test", model="test")

    assert result.status is ExternalSearchStatus.SUCCEEDED
    snapshot = ledger.snapshot()
    assert snapshot.accounted_tokens == 100_000
    assert snapshot.reported_tokens == 25


def test_selective_audit_rerun_keeps_other_cases_and_restores_order(
    tmp_path: Path,
) -> None:
    report = {
        "cases": [
            {"key": "answers_only_exam", "passed": True},
            {"key": "questions_only_exam", "passed": False},
            {"key": "course_only_question", "passed": True},
        ]
    }
    (tmp_path / "audit.json").write_text(json.dumps(report), encoding="utf-8")

    previous = _previous_results(tmp_path, {"questions_only_exam"})
    merged = _ordered_results(
        [*previous, {"key": "questions_only_exam", "passed": True}]
    )

    assert [item["key"] for item in merged] == [
        "course_only_question",
        "questions_only_exam",
        "answers_only_exam",
    ]
    assert all(item["passed"] for item in merged)
