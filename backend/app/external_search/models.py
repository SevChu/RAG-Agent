from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ExternalSearchStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    SUCCEEDED = "succeeded"
    NO_QUALIFIED_RESULTS = "no_qualified_results"
    FAILED = "failed"


class ExternalSourceQuality(StrEnum):
    ACADEMIC = "academic"
    INSTITUTIONAL = "institutional"
    OFFICIAL = "official"
    PROFESSIONAL = "professional"


@dataclass(frozen=True, slots=True)
class ExternalSearchTokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class ExternalSearchEvidence:
    rank: int
    title: str
    publisher: str
    url: str
    accessed_at: datetime
    evidence_excerpt: str
    quality: ExternalSourceQuality
    page_age: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalSearchResult:
    query: str
    status: ExternalSearchStatus
    results: tuple[ExternalSearchEvidence, ...]
    raw_result_count: int
    provider: str
    model: str
    elapsed_ms: float
    failure_reason: str | None = None
    usage: ExternalSearchTokenUsage | None = None
