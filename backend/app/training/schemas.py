from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TextValue = Annotated[str, Field(min_length=1, max_length=12000)]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]
Split = Literal["train", "validation"]
Target = Literal["scorer", "reranker"]
ReviewStatus = Literal["draft", "pending_review", "approved", "rejected", "revoked"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @field_validator("*")
    @classmethod
    def valid_unicode(cls, value: Any) -> Any:
        if isinstance(value, str):
            value.encode("utf-8")
        return value


class DatasetManifest(Contract):
    schema_version: Literal[1] = 1
    target: Target
    source: Annotated[str, Field(min_length=1, max_length=1000)]
    license_id: ShortText
    license_notes: Annotated[str, Field(min_length=1, max_length=1000)]
    training_allowed: bool = Field(strict=True)
    pii_status: Literal["pending", "clean", "redacted"]
    pii_notes: Annotated[str, Field(min_length=1, max_length=1000)]
    source_course_ids: tuple[UUID, ...] = Field(default=(), max_length=100)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("schema_version 必须为整数。")
        return value

    @field_validator("source_course_ids")
    @classmethod
    def unique_spaces(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(values)) != len(values):
            raise ValueError("资料空间不能重复。")
        return tuple(sorted(values, key=str))


class Sample(Contract):
    id: ShortText
    source_id: ShortText
    group_id: ShortText
    split: Split
    query: TextValue


class ScorerSample(Sample):
    response: TextValue
    evidence: tuple[TextValue, ...] = Field(min_length=1, max_length=20)
    score: float = Field(ge=0, le=1, allow_inf_nan=False, strict=True)


class RerankerSample(Sample):
    document: TextValue
    relevance: int = Field(ge=0, le=1, strict=True)


class Issue(Contract):
    code: str
    line: int | None = None
    related_line: int | None = None


class SplitSummary(Contract):
    count: int
    sha256: str


class ValidationReport(Contract):
    valid: bool
    approvable: bool
    content_sha256: str
    byte_count: int
    sample_count: int
    splits: dict[Split, SplitSummary]
    issues: tuple[Issue, ...]
    issue_count: int
    validator_version: Literal["training-jsonl-v1"] = "training-jsonl-v1"
    dedup_method: Literal["normalized-alnum+char5-jaccard-0.85-v1"] = (
        "normalized-alnum+char5-jaccard-0.85-v1"
    )


class DatasetCreate(Contract):
    name: Annotated[str, Field(min_length=1, max_length=100)]


class ReviewRequest(Contract):
    expected_row_version: int = Field(ge=1, strict=True)
    status: Literal["pending_review", "approved", "rejected", "revoked"]
    reviewer: ShortText
    note: Annotated[str, Field(min_length=1, max_length=2000)]


class DatasetRead(Contract):
    id: UUID
    name: str
    row_version: int
    created_at: datetime


class RevisionRead(Contract):
    id: UUID
    dataset_id: UUID
    revision_number: int
    manifest: DatasetManifest
    manifest_sha256: str
    report: ValidationReport
    status: ReviewStatus
    created_at: datetime


class ReviewRead(Contract):
    id: UUID
    revision_id: UUID
    sequence: int
    status: ReviewStatus
    reviewer: str
    note: str
    created_at: datetime


class EligibilityRead(Contract):
    revision_id: UUID
    eligible: bool
    reasons: tuple[str, ...]
    report: ValidationReport | None = None
