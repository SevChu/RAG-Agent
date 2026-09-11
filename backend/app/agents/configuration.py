"""Credential-free, immutable configuration snapshots (not HTTP request DTOs)."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class ModelSelection(FrozenConfig):
    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    model: str = Field(min_length=1, max_length=120)

    @field_validator("model")
    @classmethod
    def require_model_name(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("model must be nonblank without surrounding whitespace")
        return value


class ToolPermissions(FrozenConfig):
    web_search: bool = Field(default=True, strict=True)


class ContextPolicy(FrozenConfig):
    strategy: Literal["bounded-history-v1"] = "bounded-history-v1"
    rag_max_messages: int = Field(default=6, ge=1, le=20, strict=True)
    rag_max_chars: int = Field(default=6000, ge=500, le=30000, strict=True)
    quick_max_messages: int = Field(default=10, ge=1, le=30, strict=True)
    quick_max_chars: int = Field(default=8000, ge=500, le=40000, strict=True)


class RetrievalPolicy(FrozenConfig):
    # Online policy identity is distinct from FiQA research profiles.
    strategy: Literal["course-rag-v1"] = "course-rag-v1"
    answer_top_k: int = Field(default=6, ge=1, le=20, strict=True)
    answer_candidate_k: int = Field(default=20, ge=1, le=100, strict=True)
    summary_top_k: int = Field(default=12, ge=1, le=30, strict=True)
    summary_candidate_k: int = Field(default=40, ge=1, le=100, strict=True)
    summary_max_sources: int = Field(default=10, ge=1, le=30, strict=True)
    summary_context_max_chars: int = Field(default=8000, ge=2000, le=50000, strict=True)
    exam_top_k: int = Field(default=12, ge=1, le=30, strict=True)
    exam_candidate_k: int = Field(default=40, ge=1, le=100, strict=True)
    exam_max_sources: int = Field(default=10, ge=1, le=30, strict=True)
    exam_context_max_chars: int = Field(default=8000, ge=2000, le=50000, strict=True)
    min_similarity_score: float = Field(default=0.3, ge=-1, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_candidate_limits(self) -> Self:
        for top_k, candidate_k in (
            (self.answer_top_k, self.answer_candidate_k),
            (self.summary_top_k, self.summary_candidate_k),
            (self.exam_top_k, self.exam_candidate_k),
        ):
            if top_k > candidate_k:
                raise ValueError("top_k must not exceed candidate_k")
        return self


class EvaluationProfileRef(FrozenConfig):
    profile_id: str = Field(min_length=1, max_length=120)
    registry_version: str = Field(min_length=1, max_length=40)
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    usage: Literal["offline", "advisory"]


class AgentConfiguration(FrozenConfig):
    schema_version: Literal[1] = 1
    system_prompt: str = Field(default="", max_length=20000)
    model: ModelSelection
    # Empty grants no course access; it never means 'all courses'.
    allowed_course_ids: Annotated[tuple[UUID, ...], Field(max_length=100)] = ()
    tools: ToolPermissions = Field(default_factory=ToolPermissions)
    context: ContextPolicy = Field(default_factory=ContextPolicy)
    retrieval: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    evaluation_profiles: Annotated[tuple[EvaluationProfileRef, ...], Field(max_length=20)] = ()

    @field_validator("allowed_course_ids")
    @classmethod
    def normalize_courses(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("allowed_course_ids must be unique")
        return tuple(sorted(value, key=str))

    @field_validator("evaluation_profiles")
    @classmethod
    def normalize_evaluations(
        cls, value: tuple[EvaluationProfileRef, ...]
    ) -> tuple[EvaluationProfileRef, ...]:
        if len({item.profile_id for item in value}) != len(value):
            raise ValueError("evaluation profile IDs must be unique")
        return tuple(sorted(value, key=lambda item: item.profile_id))

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
