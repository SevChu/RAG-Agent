from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BenchmarkLifecycle(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    FROZEN = "frozen"


class BenchmarkTask(StrEnum):
    RETRIEVAL = "retrieval"
    RAG_GENERATION = "rag_generation"
    HALLUCINATION_DETECTION = "hallucination_detection"


class BenchmarkStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_count: int | None = Field(default=None, ge=0)
    query_count: int | None = Field(default=None, ge=0)
    response_count: int | None = Field(default=None, ge=0)


class BenchmarkDatasetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]+$")
    display_name: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    task: BenchmarkTask
    lifecycle: BenchmarkLifecycle
    source_url: str = Field(pattern=r"^https://")
    homepage_url: str = Field(pattern=r"^https://")
    download_url: str | None = Field(default=None, pattern=r"^https://")
    source_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    download_files: dict[str, str] = Field(default_factory=dict)
    license_name: str = Field(min_length=1)
    license_url: str = Field(pattern=r"^https://")
    license_notes: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    languages: list[str] = Field(min_length=1)
    domains: list[str] = Field(min_length=1)
    splits: list[str] = Field(min_length=1)
    expected_archive_md5: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    stats: BenchmarkStats
    approval_scope: str | None = None

    @field_validator("languages", "domains", "splits")
    @classmethod
    def validate_unique_nonblank_items(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("registry list values cannot be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("registry list values must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_approval(self) -> BenchmarkDatasetRecord:
        if self.lifecycle != BenchmarkLifecycle.CANDIDATE and not self.approval_scope:
            raise ValueError("approved datasets require an approval_scope")
        if self.lifecycle == BenchmarkLifecycle.CANDIDATE and self.approval_scope:
            raise ValueError("candidate datasets cannot declare an approval_scope")
        return self


class BenchmarkRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    datasets: list[BenchmarkDatasetRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> BenchmarkRegistry:
        ids = [item.dataset_id for item in self.datasets]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark dataset ids must be unique")
        return self

    def get(self, dataset_id: str) -> BenchmarkDatasetRecord:
        try:
            return next(item for item in self.datasets if item.dataset_id == dataset_id)
        except StopIteration as exc:
            raise KeyError(f"unknown benchmark dataset: {dataset_id}") from exc


class CorpusDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = ""
    text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class BenchmarkQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    split: str = Field(min_length=1)
    reference_answer: str | None = None
    labels: dict[str, Any] = Field(default_factory=dict)


class RelevanceJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    corpus_id: str = Field(min_length=1)
    relevance: float


class BenchmarkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    labels: dict[str, Any] = Field(default_factory=dict)
    fine_grained_labels: list[dict[str, Any]] = Field(default_factory=list)


class BenchmarkManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    dataset_id: str
    lifecycle: Literal[BenchmarkLifecycle.FROZEN]
    source_url: str
    archive_md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_bytes: int = Field(gt=0)
    files: dict[str, str]
    split_counts: dict[str, dict[str, int]]


class RagTruthManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    dataset_id: Literal["ragtruth"]
    lifecycle: Literal[BenchmarkLifecycle.FROZEN]
    source_url: str
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: dict[str, str]
    file_bytes: dict[str, int]
    split_counts: dict[str, dict[str, int]]


class RagTruthExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    split: str = Field(min_length=1)
    quality: str = Field(min_length=1)
    context: str = Field(min_length=1)
    response: str = Field(min_length=1)
    labels: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def has_hallucination(self) -> bool:
        return bool(self.labels)


class BeirAdapter:
    """Read a BEIR directory without importing or mutating the source dataset."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def iter_corpus(self) -> Iterator[CorpusDocument]:
        for payload in _iter_jsonl(self.root / "corpus.jsonl"):
            yield CorpusDocument(
                id=str(payload["_id"]),
                title=str(payload.get("title") or ""),
                text=str(payload["text"]),
                metadata=dict(payload.get("metadata") or {}),
            )

    def qrels(self, split: str) -> tuple[RelevanceJudgment, ...]:
        path = self.root / "qrels" / f"{split}.tsv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = csv.DictReader(handle, delimiter="\t")
            required = {"query-id", "corpus-id", "score"}
            if rows.fieldnames is None or not required.issubset(rows.fieldnames):
                raise ValueError(f"invalid BEIR qrels header: {path}")
            return tuple(
                RelevanceJudgment(
                    query_id=str(row["query-id"]),
                    corpus_id=str(row["corpus-id"]),
                    relevance=float(row["score"]),
                )
                for row in rows
            )

    def queries(self, split: str) -> tuple[BenchmarkQuery, ...]:
        judged_ids = {item.query_id for item in self.qrels(split)}
        queries = {
            str(payload["_id"]): str(payload["text"])
            for payload in _iter_jsonl(self.root / "queries.jsonl")
        }
        missing = judged_ids.difference(queries)
        if missing:
            raise ValueError(f"qrels reference missing queries: {', '.join(sorted(missing))}")
        return tuple(
            BenchmarkQuery(id=query_id, text=queries[query_id], split=split)
            for query_id in sorted(judged_ids)
        )

    def validate(self, splits: Iterable[str]) -> dict[str, dict[str, int]]:
        corpus_ids = {item.id for item in self.iter_corpus()}
        if not corpus_ids:
            raise ValueError("BEIR corpus is empty")
        counts: dict[str, dict[str, int]] = {}
        for split in splits:
            qrels = self.qrels(split)
            queries = self.queries(split)
            unknown_corpus = {item.corpus_id for item in qrels}.difference(corpus_ids)
            if unknown_corpus:
                raise ValueError(
                    f"qrels reference missing corpus documents: {', '.join(sorted(unknown_corpus))}"
                )
            counts[split] = {
                "queries": len(queries),
                "qrels": len(qrels),
                "relevant_qrels": sum(item.relevance > 0 for item in qrels),
            }
        counts["all"] = {"corpus": len(corpus_ids)}
        return counts


class RagTruthAdapter:
    """Read and validate the two-file RAGTruth release without executing source code."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def iter_examples(self, split: str | None = None) -> Iterator[RagTruthExample]:
        sources = {
            str(payload["source_id"]): payload
            for payload in _iter_jsonl(self.root / "source_info.jsonl")
        }
        for payload in _iter_jsonl(self.root / "response.jsonl"):
            row_split = str(payload["split"])
            if split is not None and row_split != split:
                continue
            source_id = str(payload["source_id"])
            source = sources.get(source_id)
            if source is None:
                raise ValueError(f"response references missing source: {source_id}")
            response = str(payload["response"])
            labels = list(payload.get("labels") or [])
            self._validate_labels(response, labels, str(payload["id"]))
            yield RagTruthExample(
                response_id=str(payload["id"]),
                source_id=source_id,
                task_type=str(source["task_type"]),
                source_name=str(source["source"]),
                model_name=str(payload["model"]),
                split=row_split,
                quality=str(payload["quality"]),
                context=_ragtruth_context(source["source_info"]),
                response=response,
                labels=labels,
            )

    def validate(self, splits: Iterable[str]) -> dict[str, dict[str, int]]:
        source_rows = tuple(_iter_jsonl(self.root / "source_info.jsonl"))
        source_ids = [str(payload["source_id"]) for payload in source_rows]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("RAGTruth source ids must be unique")
        examples = tuple(self.iter_examples())
        response_ids = [item.response_id for item in examples]
        if len(response_ids) != len(set(response_ids)):
            raise ValueError("RAGTruth response ids must be unique")
        counts: dict[str, dict[str, int]] = {
            "all": {
                "sources": len(source_rows),
                "responses": len(examples),
                "hallucinated_responses": sum(item.has_hallucination for item in examples),
                "spans": sum(len(item.labels) for item in examples),
            }
        }
        available = {item.split for item in examples}
        missing = set(splits).difference(available)
        if missing:
            raise ValueError(f"RAGTruth is missing splits: {', '.join(sorted(missing))}")
        for split in splits:
            selected = [item for item in examples if item.split == split]
            counts[split] = {
                "sources": len({item.source_id for item in selected}),
                "responses": len(selected),
                "hallucinated_responses": sum(item.has_hallucination for item in selected),
                "spans": sum(len(item.labels) for item in selected),
            }
        return counts

    @staticmethod
    def _validate_labels(response: str, labels: list[dict[str, Any]], response_id: str) -> None:
        for label in labels:
            start = label.get("start")
            end = label.get("end")
            text = label.get("text")
            if not isinstance(start, int) or not isinstance(end, int) or not isinstance(text, str):
                raise ValueError(f"invalid RAGTruth label in response {response_id}")
            if start < 0 or end <= start or end > len(response):
                raise ValueError(f"out-of-range RAGTruth label in response {response_id}")
            if response[start:end] != text:
                raise ValueError(f"RAGTruth label text mismatch in response {response_id}")


def load_benchmark_registry(path: Path) -> tuple[BenchmarkRegistry, str]:
    raw = path.resolve().read_bytes()
    payload: Any = json.loads(raw)
    return BenchmarkRegistry.model_validate(payload), hashlib.sha256(raw).hexdigest()


def hash_file(path: Path, algorithm: Literal["md5", "sha256"] = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_files(root: Path, relative_paths: Iterable[str]) -> dict[str, str]:
    return {
        relative_path: hash_file(root / relative_path) for relative_path in sorted(relative_paths)
    }


def _iter_jsonl(path: Path) -> Iterator[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload: Any = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL at line {line_number}: {path}") from error
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL row {line_number} is not an object: {path}")
            yield payload


def _ragtruth_context(source_info: Any) -> str:
    if isinstance(source_info, str):
        context = source_info.strip()
    elif isinstance(source_info, dict):
        context = json.dumps(source_info, ensure_ascii=False, sort_keys=True)
    else:
        raise ValueError("RAGTruth source_info must be a string or object")
    if not context:
        raise ValueError("RAGTruth context cannot be blank")
    return context
