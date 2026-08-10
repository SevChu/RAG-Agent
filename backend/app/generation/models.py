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


class AnswerScope(StrEnum):
    COURSE_AND_EXTERNAL = "course_and_external"
    COURSE_ONLY = "course_only"


class CitationSourceType(StrEnum):
    COURSE = "course"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


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
    used_external_source_ids: tuple[int, ...] = ()
    has_source_conflict: bool = False
