from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.external_search import ExternalSearchGateway, ExternalSearchResult
from app.generation import ChatCompletion, ChatCompletionGateway

MAX_AUDIT_TOKEN_BUDGET = 1_000_000
_CHAT_RETRY_MULTIPLIER = 2
_CHAT_REQUEST_OVERHEAD_TOKENS = 1024
_EXTERNAL_SEARCH_RESERVATION_TOKENS = 100_000


class BudgetExceededError(RuntimeError):
    """Raised before a model call that could exceed the approved audit budget."""


@dataclass(frozen=True, slots=True)
class TokenBudgetSnapshot:
    limit_tokens: int
    accounted_tokens: int
    reported_tokens: int
    remaining_tokens: int
    call_count: int
    unreported_call_count: int


class TokenBudgetLedger:
    """Persist conservative pre-call charges so retries cannot bypass a token cap."""

    def __init__(self, *, limit_tokens: int, path: Path | None = None) -> None:
        if not 1 <= limit_tokens <= MAX_AUDIT_TOKEN_BUDGET:
            raise ValueError(
                f"token budget must be between 1 and {MAX_AUDIT_TOKEN_BUDGET}"
            )
        self.limit_tokens = limit_tokens
        self.path = path.resolve() if path is not None else None
        self._accounted_tokens = 0
        self._reported_tokens = 0
        self._charges: list[dict[str, Any]] = []
        if self.path is not None and self.path.exists():
            self._load()

    def charge(self, *, label: str, maximum_tokens: int) -> str:
        if maximum_tokens <= 0:
            raise ValueError("maximum_tokens must be positive")
        if self._accounted_tokens + maximum_tokens > self.limit_tokens:
            raise BudgetExceededError(
                "审计 token 预算不足，已在下一次 DeepSeek 调用前停止："
                f"已计入 {self._accounted_tokens}，本次最多 {maximum_tokens}，"
                f"上限 {self.limit_tokens}。"
            )
        charge_id = str(uuid4())
        self._charges.append(
            {
                "id": charge_id,
                "label": label,
                "maximum_tokens": maximum_tokens,
                "reported_tokens": None,
                "status": "charged",
            }
        )
        self._accounted_tokens += maximum_tokens
        self._persist()
        return charge_id

    def record(self, charge_id: str, *, reported_tokens: int | None, status: str) -> None:
        charge = next(
            (item for item in self._charges if item["id"] == charge_id),
            None,
        )
        if charge is None:
            raise ValueError("unknown token budget charge")
        if charge["status"] != "charged":
            raise ValueError("token budget charge was already finalized")
        normalized = (
            reported_tokens
            if reported_tokens is not None and reported_tokens >= 0
            else None
        )
        charge["reported_tokens"] = normalized
        charge["status"] = status
        if normalized is not None:
            self._reported_tokens += normalized
        self._persist()

    def snapshot(self) -> TokenBudgetSnapshot:
        return TokenBudgetSnapshot(
            limit_tokens=self.limit_tokens,
            accounted_tokens=self._accounted_tokens,
            reported_tokens=self._reported_tokens,
            remaining_tokens=self.limit_tokens - self._accounted_tokens,
            call_count=len(self._charges),
            unreported_call_count=sum(
                item["reported_tokens"] is None for item in self._charges
            ),
        )

    def _load(self) -> None:
        assert self.path is not None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        stored_limit = int(raw["limit_tokens"])
        if stored_limit != self.limit_tokens:
            raise ValueError(
                f"existing ledger uses token budget {stored_limit}, not {self.limit_tokens}"
            )
        charges = raw.get("charges")
        if not isinstance(charges, list):
            raise ValueError("invalid token budget ledger")
        self._charges = [dict(item) for item in charges]
        self._accounted_tokens = sum(int(item["maximum_tokens"]) for item in self._charges)
        self._reported_tokens = sum(
            int(item["reported_tokens"])
            for item in self._charges
            if item.get("reported_tokens") is not None
        )
        if self._accounted_tokens > self.limit_tokens:
            raise ValueError("existing token budget ledger exceeds its limit")

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "limit_tokens": self.limit_tokens,
            "accounted_tokens": self._accounted_tokens,
            "reported_tokens": self._reported_tokens,
            "charges": self._charges,
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


class BudgetedChatCompletionGateway:
    def __init__(
        self,
        delegate: ChatCompletionGateway,
        ledger: TokenBudgetLedger,
        *,
        max_output_tokens: int,
    ) -> None:
        self.delegate = delegate
        self.ledger = ledger
        self.max_output_tokens = max_output_tokens

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        return await self._run(
            method="complete",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        return await self._run(
            method="complete_text",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
        )

    async def _run(
        self,
        *,
        method: str,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        maximum_tokens = _CHAT_RETRY_MULTIPLIER * (
            len(system_prompt)
            + len(user_prompt)
            + self.max_output_tokens
            + _CHAT_REQUEST_OVERHEAD_TOKENS
        )
        charge_id = self.ledger.charge(
            label=f"chat:{method}:{model}",
            maximum_tokens=maximum_tokens,
        )
        try:
            if method == "complete":
                completion = await self.delegate.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=model,
                )
            else:
                completion = await self.delegate.complete_text(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=model,
                )
        except Exception:
            self.ledger.record(charge_id, reported_tokens=None, status="failed")
            raise
        self.ledger.record(
            charge_id,
            reported_tokens=(
                completion.usage.total_tokens if completion.usage is not None else None
            ),
            status="completed",
        )
        return completion


class BudgetedExternalSearchGateway:
    def __init__(
        self,
        delegate: ExternalSearchGateway,
        ledger: TokenBudgetLedger,
    ) -> None:
        self.delegate = delegate
        self.ledger = ledger

    async def search(self, *, query: str, model: str) -> ExternalSearchResult:
        charge_id = self.ledger.charge(
            label=f"external_search:{model}",
            maximum_tokens=_EXTERNAL_SEARCH_RESERVATION_TOKENS,
        )
        try:
            result = await self.delegate.search(query=query, model=model)
        except Exception:
            self.ledger.record(charge_id, reported_tokens=None, status="failed")
            raise
        self.ledger.record(
            charge_id,
            reported_tokens=(result.usage.total_tokens if result.usage is not None else None),
            status=f"completed:{result.status.value}",
        )
        return result


def snapshot_dict(snapshot: TokenBudgetSnapshot) -> dict[str, int]:
    return asdict(snapshot)
