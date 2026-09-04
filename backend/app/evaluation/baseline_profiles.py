from __future__ import annotations

import math
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_BASELINE_PROFILES_PATH = Path(__file__).with_name("baseline-profiles.json")
_REQUIRED_PROFILE_IDS = {
    "fiqa-dense-retrieval",
    "ragtruth-lexical-hallucination",
    "ragtruth-nli-span-localization",
    "ragbench-lexical-dense-linear",
}


class BaselineTask(StrEnum):
    RETRIEVAL = "retrieval"
    HALLUCINATION_DETECTION = "hallucination_detection"
    TRACE_SCORING = "trace_scoring"


class FrozenModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    weight_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FrozenBaselineProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    task: BaselineTask
    method: str = Field(min_length=1)
    role: str = Field(min_length=1)
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    dataset_revision: str = Field(min_length=1)
    model: FrozenModelIdentity | None = None
    parameters: dict[str, Any] = Field(min_length=1)
    reference_metrics: dict[str, float] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    allowed_usage: tuple[str, ...] = Field(min_length=1)

    @field_validator("reference_metrics")
    @classmethod
    def validate_finite_metrics(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not math.isfinite(metric) for metric in value.values()):
            raise ValueError("baseline reference metrics must be finite")
        return value

    @field_validator("limitations", "allowed_usage")
    @classmethod
    def validate_nonblank_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("baseline profile text items cannot be blank")
        return normalized


class BaselineProfileRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    release_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    frozen_on: date
    test_policy: Literal[
        "test splits are final-report-only; optimization uses train and validation only"
    ]
    profiles: tuple[FrozenBaselineProfile, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_profiles(self) -> BaselineProfileRegistry:
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("baseline profile ids must be unique")
        missing = _REQUIRED_PROFILE_IDS.difference(profile_ids)
        if missing:
            raise ValueError(
                f"required baseline profiles are missing: {', '.join(sorted(missing))}"
            )
        if any(profile.version != self.release_version for profile in self.profiles):
            raise ValueError("all baseline profiles must match the registry release version")
        return self

    def get(self, profile_id: str) -> FrozenBaselineProfile:
        try:
            return next(profile for profile in self.profiles if profile.profile_id == profile_id)
        except StopIteration as exc:
            raise KeyError(f"unknown baseline profile: {profile_id}") from exc


def load_baseline_profiles(path: Path = DEFAULT_BASELINE_PROFILES_PATH) -> BaselineProfileRegistry:
    return BaselineProfileRegistry.model_validate_json(path.read_text(encoding="utf-8"))
