from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import pyarrow.parquet as parquet  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

RAGBENCH_SUBSETS = (
    "covidqa",
    "cuad",
    "delucionqa",
    "emanual",
    "expertqa",
    "finqa",
    "hagrid",
    "hotpotqa",
    "msmarco",
    "pubmedqa",
    "tatqa",
    "techqa",
)
RAGBENCH_SPLITS = ("train", "validation", "test")
_PUBLISHED_SCORE_FIELDS = (
    "trulens_groundedness",
    "trulens_context_relevance",
    "ragas_faithfulness",
    "ragas_context_relevance",
    "gpt3_adherence",
    "gpt3_context_relevance",
    "gpt35_utilization",
)
_REQUIRED_COLUMNS = (
    "id",
    "question",
    "documents",
    "response",
    "generation_model_name",
    "annotating_model_name",
    "dataset_name",
    "unsupported_response_sentence_keys",
    "adherence_score",
    "all_relevant_sentence_keys",
    "all_utilized_sentence_keys",
    "relevance_score",
    "utilization_score",
    "completeness_score",
    *_PUBLISHED_SCORE_FIELDS,
)


def ragbench_relative_files() -> tuple[str, ...]:
    return tuple(
        f"{subset}/{split}-00000-of-00001.parquet"
        for subset in RAGBENCH_SUBSETS
        for split in RAGBENCH_SPLITS
    )


class RagBenchManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    dataset_id: Literal["ragbench"]
    lifecycle: Literal["frozen"]
    source_url: str
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: dict[str, str]
    file_bytes: dict[str, int]
    split_counts: dict[str, dict[str, int]]
    subsets: tuple[str, ...]


class RagBenchExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_id: str = Field(min_length=1)
    row_index: int = Field(ge=0)
    subset: str = Field(min_length=1)
    split: str = Field(min_length=1)
    question: str = Field(min_length=1)
    documents: tuple[str, ...] = Field(min_length=1)
    response: str = Field(min_length=1)
    generation_model_name: str = Field(min_length=1)
    annotating_model_name: str | None
    adherence_score: bool | None
    relevance_score: float | None = Field(default=None, ge=0.0)
    utilization_score: float | None = Field(default=None, ge=0.0)
    completeness_score: float | None = Field(default=None, ge=0.0)
    unsupported_response_sentence_keys: tuple[str, ...] | None
    all_relevant_sentence_keys: tuple[str, ...] | None
    all_utilized_sentence_keys: tuple[str, ...] | None
    published_scores: dict[str, float | None]


class RagBenchAdapter:
    """Read the fixed Parquet release without executing remote dataset code."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def iter_examples(
        self,
        *,
        split: str | None = None,
        subset: str | None = None,
    ) -> Iterator[RagBenchExample]:
        selected_splits = _selected_values(split, RAGBENCH_SPLITS, "split")
        selected_subsets = _selected_values(subset, RAGBENCH_SUBSETS, "subset")
        for subset_name in selected_subsets:
            for split_name in selected_splits:
                path = self.root / subset_name / f"{split_name}-00000-of-00001.parquet"
                parquet_file = parquet.ParquetFile(path)
                missing = set(_REQUIRED_COLUMNS).difference(parquet_file.schema_arrow.names)
                if missing:
                    raise ValueError(
                        f"RAGBench file is missing columns: {path}: {', '.join(sorted(missing))}"
                    )
                row_index = 0
                for batch in parquet_file.iter_batches(
                    batch_size=512,
                    columns=list(_REQUIRED_COLUMNS),
                ):
                    for row in batch.to_pylist():
                        yield _parse_example(row, subset_name, split_name, row_index)
                        row_index += 1

    def validate(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {
            "all": {"responses": 0, "labeled_responses": 0, "adherent_responses": 0},
            **{
                split: {"responses": 0, "labeled_responses": 0, "adherent_responses": 0}
                for split in RAGBENCH_SPLITS
            },
        }
        for subset in RAGBENCH_SUBSETS:
            for split in RAGBENCH_SPLITS:
                key = f"{subset}/{split}"
                counts[key] = {
                    "responses": 0,
                    "labeled_responses": 0,
                    "adherent_responses": 0,
                }
                for example in self.iter_examples(split=split, subset=subset):
                    labels = (
                        example.adherence_score,
                        example.relevance_score,
                        example.utilization_score,
                        example.completeness_score,
                    )
                    if any(value is None for value in labels) and not all(
                        value is None for value in labels
                    ):
                        raise ValueError("RAGBench row has partially missing gold labels")
                    labeled = int(all(value is not None for value in labels))
                    adherent = int(example.adherence_score is True)
                    for count_key in (key, split, "all"):
                        counts[count_key]["responses"] += 1
                        counts[count_key]["labeled_responses"] += labeled
                        counts[count_key]["adherent_responses"] += adherent
        return counts


def _selected_values(
    selected: str | None,
    available: Sequence[str],
    label: str,
) -> tuple[str, ...]:
    if selected is None:
        return tuple(available)
    if selected not in available:
        raise ValueError(f"unknown RAGBench {label}: {selected}")
    return (selected,)


def _parse_example(
    row: Mapping[str, Any],
    subset: str,
    split: str,
    row_index: int,
) -> RagBenchExample:
    raw_dataset_name = row["dataset_name"]
    dataset_name = "" if raw_dataset_name is None else str(raw_dataset_name).strip().lower()
    expected_dataset_names = {subset, f"{subset}_{split}"}
    if dataset_name and dataset_name not in expected_dataset_names:
        raise ValueError(
            f"RAGBench dataset_name mismatch: expected {subset} or {subset}_{split}, "
            f"got {dataset_name}"
        )
    published = {field: _optional_score(row.get(field), field) for field in _PUBLISHED_SCORE_FIELDS}
    return RagBenchExample(
        example_id=_required_text(row["id"], "id"),
        row_index=row_index,
        subset=subset,
        split=split,
        question=_required_text(row["question"], "question"),
        documents=_required_text_sequence(row["documents"], "documents"),
        response=_required_text(row["response"], "response"),
        generation_model_name=_required_text(
            row["generation_model_name"],
            "generation_model_name",
        ),
        annotating_model_name=_optional_text(
            row["annotating_model_name"],
            "annotating_model_name",
        ),
        adherence_score=_optional_bool(row["adherence_score"], "adherence_score"),
        relevance_score=_optional_required_score(row["relevance_score"], "relevance_score"),
        utilization_score=_optional_required_score(
            row["utilization_score"],
            "utilization_score",
        ),
        completeness_score=_optional_required_score(
            row["completeness_score"],
            "completeness_score",
        ),
        unsupported_response_sentence_keys=_optional_string_sequence(
            row["unsupported_response_sentence_keys"],
            "unsupported_response_sentence_keys",
        ),
        all_relevant_sentence_keys=_optional_string_sequence(
            row["all_relevant_sentence_keys"],
            "all_relevant_sentence_keys",
        ),
        all_utilized_sentence_keys=_optional_string_sequence(
            row["all_utilized_sentence_keys"],
            "all_utilized_sentence_keys",
        ),
        published_scores=published,
    )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"RAGBench {field} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _required_text_sequence(value: Any, field: str) -> tuple[str, ...]:
    items = _string_sequence(value, field)
    if not items or any(not item.strip() for item in items):
        raise ValueError(f"RAGBench {field} must contain non-empty strings")
    return items


def _optional_string_sequence(value: Any, field: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _string_sequence(value, field)


def _string_sequence(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"RAGBench {field} must be a list of strings")
    return tuple(value)


def _optional_bool(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    return _required_bool(value, field)


def _required_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"RAGBench {field} must be boolean")
    return value


def _optional_required_score(value: Any, field: str) -> float | None:
    if value is None:
        return None
    return _required_score(value, field)


def _required_score(value: Any, field: str) -> float:
    score = _numeric(value, field)
    if score < 0.0:
        raise ValueError(f"RAGBench {field} must be non-negative")
    return score


def _optional_score(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"RAGBench {field} must be numeric or null")
    score = float(value)
    return score if math.isfinite(score) else None


def _numeric(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"RAGBench {field} must be numeric")
    score = float(value)
    if not math.isfinite(score):
        raise ValueError(f"RAGBench {field} must be finite")
    return score
