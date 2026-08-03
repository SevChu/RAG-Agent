from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AnswerStyle(StrEnum):
    CONCISE = "concise"
    BALANCED = "balanced"
    DETAILED = "detailed"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    content: str
    model: str
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    status: AnswerStatus
    used_source_ids: tuple[int, ...]
    model: str | None
    usage: TokenUsage | None = None
