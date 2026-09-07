from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import psutil  # type: ignore[import-untyped]
import torch
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    RagTruthAdapter,
    RagTruthExample,
    RagTruthManifest,
    add_char_confusion,
    binary_metrics,
    build_lexical_context,
    char_labels,
    context_chunks,
    expected_calibration_error,
    hash_file,
    hash_files,
    lexical_feature_vector,
    metrics_from_confusion,
    predicted_char_labels,
    sentence_spans,
    split_train_dev_sources,
)
from app.evaluation.hallucination import TextSpan  # noqa: E402
from app.evaluation.run_store import write_json_atomic  # noqa: E402
from scripts.benchmark_runtime import (  # noqa: E402
    hardware_info,
    model_identity,
    resolve_device,
)

DATASET_ROOT = _BACKEND_ROOT / "datasets" / "benchmarks" / "ragtruth"
DEFAULT_OUTPUT = DATASET_ROOT / "runs" / "week05-day04-ragtruth"
DEFAULT_EMBEDDING_MODEL = _REPO_ROOT / "data" / "models" / "embedding" / "bge-m3"
SEED = 42
DEV_FRACTION = 0.2
CONTEXT_CHUNK_CHARS = 1200
CONTEXT_OVERLAP_CHARS = 120
EMBEDDING_BATCH_SIZE = 8
FEATURE_NAMES = (
    "token_coverage",
    "content_token_coverage",
    "bigram_coverage",
    "unsupported_number_ratio",
    "unsupported_capitalized_ratio",
    "negation_mismatch",
    "response_token_length",
    "context_token_length",
    "dense_support",
)


@dataclass(frozen=True, slots=True)
class SentenceRecord:
    example_position: int
    source_id: str
    span: TextSpan
    label: int
    lexical_features: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class Thresholds:
    response: float
    span: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic RAGTruth hallucination-detection baselines"
    )
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--embedding-batch-size", type=int, default=EMBEDDING_BATCH_SIZE)
    parser.add_argument("--force-dense", action="store_true")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.embedding_batch_size < 1:
        raise ValueError("embedding batch size must be positive")

    started = time.perf_counter()
    process = psutil.Process()
    dataset_root = arguments.dataset_root.resolve()
    manifest = verify_frozen_dataset(dataset_root)
    examples = tuple(RagTruthAdapter(dataset_root / "raw").iter_examples())
    source_contexts = unique_source_contexts(examples)
    records, record_indices = build_sentence_records(examples)

    source_tasks = {item.source_id: item.task_type for item in examples if item.split == "train"}
    dev_sources = split_train_dev_sources(
        source_tasks,
        seed=SEED,
        dev_fraction=DEV_FRACTION,
    )
    fit_examples = tuple(
        index
        for index, item in enumerate(examples)
        if item.split == "train" and item.source_id not in dev_sources
    )
    dev_examples = tuple(
        index
        for index, item in enumerate(examples)
        if item.split == "train" and item.source_id in dev_sources
    )
    test_examples = tuple(index for index, item in enumerate(examples) if item.split == "test")

    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    dense_started = time.perf_counter()
    dense_support, dense_metadata = load_or_compute_dense_support(
        records=records,
        source_contexts=source_contexts,
        model_path=arguments.embedding_model.resolve(),
        output=output,
        device_preference=arguments.device,
        batch_size=arguments.embedding_batch_size,
        manifest=manifest,
        force=arguments.force_dense,
    )
    dense_seconds = time.perf_counter() - dense_started

    lexical_matrix = np.asarray(
        [record.lexical_features for record in records],
        dtype=np.float64,
    )
    feature_matrix = np.column_stack((lexical_matrix, dense_support))
    labels = np.asarray([record.label for record in records], dtype=np.int64)
    fit_record_indices = flatten_record_indices(record_indices, fit_examples)
    model = LogisticRegression(
        class_weight="balanced",
        max_iter=1000,
        random_state=SEED,
        solver="lbfgs",
    )
    fit_started = time.perf_counter()
    model.fit(feature_matrix[fit_record_indices], labels[fit_record_indices])
    fit_seconds = time.perf_counter() - fit_started

    lexical_support = (
        0.30 * lexical_matrix[:, 0] + 0.50 * lexical_matrix[:, 1] + 0.20 * lexical_matrix[:, 2]
    )
    method_scores: dict[str, NDArray[np.float64]] = {
        "lexical_coverage": np.clip(1.0 - lexical_support, 0.0, 1.0),
        "bge_m3_dense": np.clip(1.0 - dense_support, 0.0, 1.0),
        "logistic_fusion": np.asarray(
            model.predict_proba(feature_matrix)[:, 1],
            dtype=np.float64,
        ),
    }
    thresholds = {
        name: tune_thresholds(
            scores=scores,
            examples=examples,
            records=records,
            record_indices=record_indices,
            selected_examples=dev_examples,
        )
        for name, scores in method_scores.items()
    }
    results = {
        name: evaluate_method(
            scores=scores,
            thresholds=thresholds[name],
            examples=examples,
            records=records,
            record_indices=record_indices,
            selected_examples=test_examples,
        )
        for name, scores in method_scores.items()
    }

    prediction_path = output / "test-predictions.jsonl"
    write_predictions(
        prediction_path,
        examples=examples,
        records=records,
        record_indices=record_indices,
        test_examples=test_examples,
        method_scores=method_scores,
        thresholds=thresholds,
    )
    summary = build_summary(
        manifest=manifest,
        examples=examples,
        fit_examples=fit_examples,
        dev_examples=dev_examples,
        dev_sources=dev_sources,
        test_examples=test_examples,
        results=results,
        thresholds=thresholds,
        model=model,
        fit_seconds=fit_seconds,
        dense_metadata=dense_metadata,
        dense_seconds=dense_seconds,
        process=process,
        wall_seconds=time.perf_counter() - started,
        prediction_path=prediction_path,
    )
    summary_path = output / "summary.json"
    write_json_atomic(summary_path, summary)
    print(json.dumps(compact_results(summary), ensure_ascii=False, indent=2))
    print(f"summary: {summary_path}")
    return 0


def verify_frozen_dataset(dataset_root: Path) -> RagTruthManifest:
    manifest_path = dataset_root / "manifest.json"
    raw_root = dataset_root / "raw"
    frozen = RagTruthManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if hash_files(raw_root, ("response.jsonl", "source_info.jsonl")) != frozen.files:
        raise ValueError("RAGTruth files differ from the frozen manifest")
    if RagTruthAdapter(raw_root).validate(("train", "test")) != frozen.split_counts:
        raise ValueError("RAGTruth counts differ from the frozen manifest")
    return frozen


def unique_source_contexts(examples: Sequence[RagTruthExample]) -> dict[str, str]:
    contexts: dict[str, str] = {}
    for example in examples:
        existing = contexts.setdefault(example.source_id, example.context)
        if existing != example.context:
            raise ValueError(f"RAGTruth source context changed within source {example.source_id}")
    return contexts


def build_sentence_records(
    examples: Sequence[RagTruthExample],
) -> tuple[tuple[SentenceRecord, ...], tuple[tuple[int, ...], ...]]:
    records: list[SentenceRecord] = []
    indices: list[tuple[int, ...]] = []
    prepared_contexts = {item.source_id: build_lexical_context(item.context) for item in examples}
    for example_position, example in enumerate(examples):
        current: list[int] = []
        for span in sentence_spans(example.response):
            label = int(
                any(
                    span.start < int(item["end"]) and span.end > int(item["start"])
                    for item in example.labels
                )
            )
            current.append(len(records))
            records.append(
                SentenceRecord(
                    example_position=example_position,
                    source_id=example.source_id,
                    span=span,
                    label=label,
                    lexical_features=lexical_feature_vector(
                        prepared_contexts[example.source_id], span.text
                    ),
                )
            )
        if not current:
            raise ValueError(f"RAGTruth response has no sentence: {example.response_id}")
        indices.append(tuple(current))
    return tuple(records), tuple(indices)


def flatten_record_indices(
    record_indices: Sequence[Sequence[int]],
    example_positions: Sequence[int],
) -> NDArray[np.int64]:
    return np.asarray(
        [
            record_index
            for example_position in example_positions
            for record_index in record_indices[example_position]
        ],
        dtype=np.int64,
    )


def load_or_compute_dense_support(
    *,
    records: Sequence[SentenceRecord],
    source_contexts: Mapping[str, str],
    model_path: Path,
    output: Path,
    device_preference: str,
    batch_size: int,
    manifest: RagTruthManifest,
    force: bool,
) -> tuple[NDArray[np.float64], dict[str, Any]]:
    identity = model_identity(model_path)
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "dataset_files": manifest.files,
                "model": identity,
                "context_chunk_chars": CONTEXT_CHUNK_CHARS,
                "context_overlap_chars": CONTEXT_OVERLAP_CHARS,
                "sentence_count": len(records),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cache_path = output / "dense-support.npz"
    if cache_path.exists() and not force:
        with np.load(cache_path, allow_pickle=False) as cached:
            stored_key = str(cached["cache_key"].item())
            scores = np.asarray(cached["scores"], dtype=np.float64)
        if stored_key == cache_key and scores.shape == (len(records),):
            return scores, {
                "cache": "hit",
                "cache_key": cache_key,
                "cache_sha256": hash_file(cache_path),
                "model": identity,
                "batch_size": batch_size,
            }

    device = resolve_device(device_preference)
    model_kwargs: dict[str, Any] | None = None
    if device == "cuda":
        model_kwargs = {"torch_dtype": torch.float16}
    model = SentenceTransformer(
        str(model_path),
        device=device,
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs=model_kwargs,
    )
    chunk_texts: list[str] = []
    source_slices: dict[str, slice] = {}
    for source_id in sorted(source_contexts):
        chunks = context_chunks(
            source_contexts[source_id],
            max_chars=CONTEXT_CHUNK_CHARS,
            overlap_chars=CONTEXT_OVERLAP_CHARS,
        )
        start = len(chunk_texts)
        chunk_texts.extend(chunks)
        source_slices[source_id] = slice(start, len(chunk_texts))

    context_vectors = np.asarray(
        model.encode(
            chunk_texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ),
        dtype=np.float32,
    )
    sentence_vectors = np.asarray(
        model.encode(
            [record.span.text for record in records],
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ),
        dtype=np.float32,
    )
    scores = np.empty(len(records), dtype=np.float64)
    for position, (record, vector) in enumerate(zip(records, sentence_vectors, strict=True)):
        candidates = context_vectors[source_slices[record.source_id]]
        scores[position] = float(np.max(candidates @ vector))

    np.savez_compressed(cache_path, cache_key=np.asarray(cache_key), scores=scores)
    return scores, {
        "cache": "miss",
        "cache_key": cache_key,
        "cache_sha256": hash_file(cache_path),
        "model": identity,
        "device": device,
        "batch_size": batch_size,
        "context_chunks": len(chunk_texts),
        "response_sentences": len(records),
    }


def tune_thresholds(
    *,
    scores: NDArray[np.float64],
    examples: Sequence[RagTruthExample],
    records: Sequence[SentenceRecord],
    record_indices: Sequence[Sequence[int]],
    selected_examples: Sequence[int],
) -> Thresholds:
    response_labels = [int(examples[index].has_hallucination) for index in selected_examples]
    response_scores = [
        float(max(scores[position] for position in record_indices[index]))
        for index in selected_examples
    ]
    response_threshold = select_response_threshold(
        response_labels,
        response_scores,
        np.linspace(0.0, 1.0, 201),
    )
    span_threshold = select_span_threshold(
        scores=scores,
        examples=examples,
        records=records,
        record_indices=record_indices,
        selected_examples=selected_examples,
        candidates=np.linspace(0.0, 1.0, 101),
    )
    return Thresholds(response=response_threshold, span=span_threshold)


def select_response_threshold(
    labels: Sequence[int],
    scores: Sequence[float],
    candidates: Iterable[float],
) -> float:
    best = (-1.0, -1.0, -1.0)
    selected = 0.5
    for threshold in candidates:
        predictions = [int(score >= threshold) for score in scores]
        metrics = binary_metrics(labels, predictions)
        rank = (metrics.f1, metrics.precision, float(threshold))
        if rank > best:
            best = rank
            selected = float(threshold)
    return selected


def select_span_threshold(
    *,
    scores: NDArray[np.float64],
    examples: Sequence[RagTruthExample],
    records: Sequence[SentenceRecord],
    record_indices: Sequence[Sequence[int]],
    selected_examples: Sequence[int],
    candidates: Iterable[float],
) -> float:
    selected = 0.5
    best = (-1.0, -1.0, -1.0)
    expected = {
        index: char_labels(len(examples[index].response), examples[index].labels)
        for index in selected_examples
    }
    for threshold in candidates:
        counts = [0, 0, 0, 0]
        for index in selected_examples:
            spans = (
                records[position].span
                for position in record_indices[index]
                if scores[position] >= threshold
            )
            predicted = predicted_char_labels(len(examples[index].response), spans)
            add_char_confusion(counts, expected[index], predicted)
        metrics = metrics_from_confusion(counts)
        rank = (metrics.f1, metrics.precision, float(threshold))
        if rank > best:
            best = rank
            selected = float(threshold)
    return selected


def evaluate_method(
    *,
    scores: NDArray[np.float64],
    thresholds: Thresholds,
    examples: Sequence[RagTruthExample],
    records: Sequence[SentenceRecord],
    record_indices: Sequence[Sequence[int]],
    selected_examples: Sequence[int],
) -> dict[str, Any]:
    response_labels = [int(examples[index].has_hallucination) for index in selected_examples]
    response_scores = [
        float(max(scores[position] for position in record_indices[index]))
        for index in selected_examples
    ]
    response_predictions = [int(score >= thresholds.response) for score in response_scores]
    response = response_metric_payload(response_labels, response_scores, response_predictions)

    by_task: dict[str, Any] = {}
    for task in sorted({examples[index].task_type for index in selected_examples}):
        positions = [
            position
            for position, index in enumerate(selected_examples)
            if examples[index].task_type == task
        ]
        by_task[task] = response_metric_payload(
            [response_labels[position] for position in positions],
            [response_scores[position] for position in positions],
            [response_predictions[position] for position in positions],
        )

    span_counts = [0, 0, 0, 0]
    for index in selected_examples:
        expected = char_labels(len(examples[index].response), examples[index].labels)
        spans = (
            records[position].span
            for position in record_indices[index]
            if scores[position] >= thresholds.span
        )
        predicted = predicted_char_labels(len(examples[index].response), spans)
        add_char_confusion(span_counts, expected, predicted)
    return {
        "response": response,
        "response_by_task": by_task,
        "span_char": asdict(metrics_from_confusion(span_counts)),
    }


def response_metric_payload(
    labels: Sequence[int],
    scores: Sequence[float],
    predictions: Sequence[int],
) -> dict[str, Any]:
    return {
        **asdict(binary_metrics(labels, predictions)),
        "auroc": float(roc_auc_score(labels, scores)),
        "auprc": float(average_precision_score(labels, scores)),
        "brier": float(brier_score_loss(labels, scores)),
        "ece_10": expected_calibration_error(labels, scores, bins=10),
        "positive_rate": sum(labels) / len(labels),
        "predicted_positive_rate": sum(predictions) / len(predictions),
        "count": len(labels),
    }


def write_predictions(
    path: Path,
    *,
    examples: Sequence[RagTruthExample],
    records: Sequence[SentenceRecord],
    record_indices: Sequence[Sequence[int]],
    test_examples: Sequence[int],
    method_scores: Mapping[str, NDArray[np.float64]],
    thresholds: Mapping[str, Thresholds],
) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for index in test_examples:
            example = examples[index]
            methods: dict[str, Any] = {}
            for name, scores in method_scores.items():
                sentences = [
                    {
                        "start": records[position].span.start,
                        "end": records[position].span.end,
                        "score": float(scores[position]),
                        "predicted_hallucination": bool(scores[position] >= thresholds[name].span),
                    }
                    for position in record_indices[index]
                ]
                response_score = max(item["score"] for item in sentences)
                methods[name] = {
                    "response_score": response_score,
                    "predicted_hallucination": bool(response_score >= thresholds[name].response),
                    "sentences": sentences,
                }
            handle.write(
                json.dumps(
                    {
                        "response_id": example.response_id,
                        "source_id": example.source_id,
                        "task_type": example.task_type,
                        "model_name": example.model_name,
                        "gold_hallucination": example.has_hallucination,
                        "gold_spans": example.labels,
                        "methods": methods,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    temporary.replace(path)


def build_summary(
    *,
    manifest: RagTruthManifest,
    examples: Sequence[RagTruthExample],
    fit_examples: Sequence[int],
    dev_examples: Sequence[int],
    dev_sources: Collection[str],
    test_examples: Sequence[int],
    results: Mapping[str, Any],
    thresholds: Mapping[str, Thresholds],
    model: LogisticRegression,
    fit_seconds: float,
    dense_metadata: Mapping[str, Any],
    dense_seconds: float,
    process: psutil.Process,
    wall_seconds: float,
    prediction_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "benchmark": "ragtruth",
        "protocol": {
            "source_revision": manifest.source_revision,
            "dataset_files": manifest.files,
            "official_test_untouched": True,
            "test_sources": len({examples[index].source_id for index in test_examples}),
            "test_responses": len(test_examples),
            "fit_sources": len({examples[index].source_id for index in fit_examples}),
            "fit_responses": len(fit_examples),
            "dev_sources": len(dev_sources),
            "dev_responses": len(dev_examples),
            "split_group": "source_id",
            "dev_fraction": DEV_FRACTION,
            "seed": SEED,
            "span_metric": "micro char-level overlap",
            "implicit_true_policy": "kept as unsupported, matching release labels",
            "sentence_prediction_boundary": True,
        },
        "methods": {
            name: {
                "thresholds": asdict(thresholds[name]),
                **payload,
            }
            for name, payload in results.items()
        },
        "logistic_fusion": {
            "feature_names": FEATURE_NAMES,
            "coefficients": {
                name: float(value)
                for name, value in zip(FEATURE_NAMES, model.coef_[0], strict=True)
            },
            "intercept": float(model.intercept_[0]),
            "class_weight": "balanced",
            "fit_seconds": fit_seconds,
        },
        "dense": {**dense_metadata, "wall_seconds": dense_seconds},
        "published_reference": {
            "response_f1": {
                "gpt_4_turbo_prompt": 0.634,
                "selfcheckgpt_gpt_3_5": 0.588,
                "finetuned_llama_2_13b": 0.787,
            },
            "span_char_f1": {
                "gpt_4_turbo_prompt": 0.283,
                "finetuned_llama_2_13b": 0.527,
            },
            "comparison_note": (
                "Context only: methods, prompts and compute differ from local baselines."
            ),
        },
        "runtime": {
            "wall_seconds": wall_seconds,
            "peak_working_set_bytes": process.memory_info().peak_wset,
            "hardware": hardware_info(),
            "external_api_calls": 0,
            "external_tokens": 0,
            "new_model_downloads": 0,
        },
        "artifacts": {
            "predictions": prediction_path.name,
            "predictions_sha256": hash_file(prediction_path),
        },
    }


def compact_results(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: {
            "response_f1": payload["response"]["f1"],
            "response_auroc": payload["response"]["auroc"],
            "response_auprc": payload["response"]["auprc"],
            "span_char_f1": payload["span_char"]["f1"],
            "response_threshold": payload["thresholds"]["response"],
            "span_threshold": payload["thresholds"]["span"],
        }
        for name, payload in summary["methods"].items()
    }


if __name__ == "__main__":
    raise SystemExit(main())
