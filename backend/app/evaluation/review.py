from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HumanAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=r"^W5-\d{3}$")
    review_status: Literal["pending", "verified", "rejected"] = "pending"
    reference_answer: str = ""
    key_points: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    notes: str = ""

    @model_validator(mode="after")
    def require_verified_review_metadata(self) -> HumanAnnotation:
        if self.review_status == "verified" and (
            not self.reference_answer.strip() or not (self.reviewer or "").strip()
        ):
            raise ValueError("verified annotations require an answer and reviewer")
        return self


class HumanAnnotationFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    dataset_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    instructions: str
    cases: list[HumanAnnotation]


class JudgeCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=r"^W5-\d{3}$")
    verdict: Literal["pass", "fail", "uncertain"]
    scores: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


class JudgeResultFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_model: str = Field(min_length=1)
    judge_prompt_version: str = Field(min_length=1)
    generated_at: datetime
    cases: list[JudgeCaseResult]


def load_human_annotations(
    path: Path,
    *,
    dataset_sha256: str,
    known_case_ids: set[str],
) -> HumanAnnotationFile:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    annotations = HumanAnnotationFile.model_validate(payload)
    if annotations.dataset_sha256 != dataset_sha256:
        raise ValueError("human annotations belong to a different dataset version")
    _validate_case_ids(
        [item.case_id for item in annotations.cases],
        known_case_ids=known_case_ids,
        layer="human annotations",
    )
    return annotations


def load_judge_results(
    path: Path,
    *,
    dataset_sha256: str,
    known_case_ids: set[str],
) -> JudgeResultFile:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    results = JudgeResultFile.model_validate(payload)
    if results.dataset_sha256 != dataset_sha256:
        raise ValueError("judge results belong to a different dataset version")
    _validate_case_ids(
        [item.case_id for item in results.cases],
        known_case_ids=known_case_ids,
        layer="judge results",
    )
    return results


def merge_review_layers(
    results: list[dict[str, Any]],
    *,
    human: HumanAnnotationFile,
    judge: JudgeResultFile | None,
) -> list[dict[str, Any]]:
    human_by_id = {item.case_id: item for item in human.cases}
    judge_by_id = {item.case_id: item for item in judge.cases} if judge else {}
    merged: list[dict[str, Any]] = []
    for source in results:
        row = copy.deepcopy(source)
        case_id = str(row.get("case_id") or "")
        annotation = human_by_id.get(case_id)
        row["human_review"] = (
            annotation.model_dump(mode="json") if annotation is not None else None
        )
        judge_result = judge_by_id.get(case_id)
        row["llm_judge"] = (
            judge_result.model_dump(mode="json") if judge_result is not None else None
        )
        merged.append(row)
    return merged


def _validate_case_ids(
    case_ids: list[str],
    *,
    known_case_ids: set[str],
    layer: str,
) -> None:
    if len(set(case_ids)) != len(case_ids):
        raise ValueError(f"{layer} contain duplicate case ids")
    unknown = set(case_ids).difference(known_case_ids)
    if unknown:
        raise ValueError(f"{layer} contain unknown cases: {', '.join(sorted(unknown))}")
