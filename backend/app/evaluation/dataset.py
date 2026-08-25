from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvaluationSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class EvaluationCategory(StrEnum):
    COURSE_QA = "course_qa"
    REFUSAL = "refusal"
    MIXED_SOURCE = "mixed_source"
    DYNAMIC_SUMMARY = "dynamic_summary"
    MIXED_EXAM = "mixed_exam"
    MULTI_TURN = "multi_turn"
    COURSE_ISOLATION = "course_isolation"


class EvaluationBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    git_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    context_max_messages: int = Field(ge=1)
    context_max_chars: int = Field(ge=1)
    course_memory_enabled: bool = False


class EvaluationExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: Literal["question", "summary", "exam"]
    status: Literal["answered", "insufficient_evidence"]
    candidate_answer: str = Field(min_length=1)
    annotation_status: Literal["candidate", "verified"] = "candidate"
    key_points: list[str] = Field(default_factory=list)
    source_targets: list[str] = Field(default_factory=list)
    forbidden_source_targets: list[str] = Field(default_factory=list)
    forbidden_answer_terms: list[str] = Field(default_factory=list)
    requires_citations: bool = True
    external_search: Literal["required", "forbidden", "optional"] = "forbidden"
    question_count: int | None = Field(default=None, ge=1, le=20)
    include_answers: bool | None = None
    include_explanations: bool | None = None

    @field_validator(
        "key_points",
        "source_targets",
        "forbidden_source_targets",
        "forbidden_answer_terms",
    )
    @classmethod
    def normalize_string_lists(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("list values cannot be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("list values must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_task_specific_fields(self) -> EvaluationExpectation:
        exam_fields = (
            self.question_count,
            self.include_answers,
            self.include_explanations,
        )
        if self.task_type == "exam" and any(value is None for value in exam_fields):
            raise ValueError("exam expectations require count and output switches")
        if self.task_type != "exam" and any(value is not None for value in exam_fields):
            raise ValueError("exam fields are only valid for exam cases")
        if self.status == "insufficient_evidence" and self.requires_citations:
            raise ValueError("insufficient-evidence cases cannot require citations")
        return self


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^W5-\d{3}$")
    split: EvaluationSplit
    category: EvaluationCategory
    partition_key: str = Field(min_length=1)
    turns: list[str] = Field(min_length=1, max_length=12)
    answer_scope: Literal["course_only", "course_and_external"]
    expected: EvaluationExpectation
    provenance: list[str] = Field(default_factory=list)

    @field_validator("partition_key")
    @classmethod
    def normalize_partition_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("partition_key cannot be blank")
        return normalized

    @field_validator("turns", "provenance")
    @classmethod
    def normalize_text_lists(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("text values cannot be blank")
        return normalized

    @property
    def final_question(self) -> str:
        return self.turns[-1]


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    course_name: str = Field(min_length=1)
    baseline: EvaluationBaseline
    split_policy: str = Field(min_length=1)
    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dataset_isolation(self) -> EvaluationDataset:
        case_ids = [case.id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("evaluation case ids must be unique")
        partition_splits: dict[str, EvaluationSplit] = {}
        for case in self.cases:
            previous = partition_splits.setdefault(case.partition_key, case.split)
            if previous != case.split:
                raise ValueError(
                    f"partition {case.partition_key!r} crosses {previous} and {case.split}"
                )
        return self

    def select(
        self,
        *,
        splits: set[EvaluationSplit] | None = None,
        case_ids: set[str] | None = None,
        limit: int | None = None,
    ) -> tuple[EvaluationCase, ...]:
        selected = tuple(
            case
            for case in self.cases
            if (splits is None or case.split in splits)
            and (case_ids is None or case.id in case_ids)
        )
        if case_ids is not None:
            missing = case_ids.difference(case.id for case in selected)
            if missing:
                raise ValueError(f"unknown or excluded cases: {', '.join(sorted(missing))}")
        return selected[:limit] if limit is not None else selected


def load_evaluation_dataset(path: Path) -> tuple[EvaluationDataset, str]:
    resolved = path.resolve()
    raw = resolved.read_bytes()
    payload: Any = json.loads(raw)
    return EvaluationDataset.model_validate(payload), hashlib.sha256(raw).hexdigest()


def dataset_summary(dataset: EvaluationDataset) -> dict[str, Any]:
    split_counts = {
        split.value: sum(case.split == split for case in dataset.cases)
        for split in EvaluationSplit
    }
    category_counts = {
        category.value: sum(case.category == category for case in dataset.cases)
        for category in EvaluationCategory
    }
    annotation_counts = {
        status: sum(case.expected.annotation_status == status for case in dataset.cases)
        for status in ("candidate", "verified")
    }
    return {
        "dataset_id": dataset.dataset_id,
        "version": dataset.version,
        "case_count": len(dataset.cases),
        "split_counts": split_counts,
        "category_counts": category_counts,
        "annotation_counts": annotation_counts,
        "partition_count": len({case.partition_key for case in dataset.cases}),
    }
