from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import numpy as np
import psutil  # type: ignore[import-untyped]
import torch
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from transformers import AutoModelForSequenceClassification, AutoTokenizer

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    ExperimentStatus,
    OptimizationSplit,
    RagTruthAdapter,
    RagTruthExample,
    RagTruthManifest,
    SliceClass,
    SliceObservation,
    aggregate_slices,
    char_labels,
    context_chunks,
    hash_file,
    load_experiment_registry,
    metrics_from_confusion,
    predicted_char_labels,
    require_optimization_split,
)
from app.evaluation.run_store import write_json_atomic  # noqa: E402
from scripts.run_hallucination_benchmark import (  # noqa: E402
    CONTEXT_CHUNK_CHARS,
    CONTEXT_OVERLAP_CHARS,
    EMBEDDING_BATCH_SIZE,
    FEATURE_NAMES,
    SentenceRecord,
    Thresholds,
    build_sentence_records,
    evaluate_method,
    flatten_record_indices,
    hardware_info,
    load_or_compute_dense_support,
    model_identity,
    resolve_device,
    tune_thresholds,
    unique_source_contexts,
)

EXPERIMENT_ID = "w6-d4-sentence-nli-spans"
OPTIMIZATION_SPLITS = ("train", "validation")
DEFAULT_DATASET = _BACKEND_ROOT / "datasets/benchmarks/ragtruth/derived/train-only"
DEFAULT_OUTPUT = _BACKEND_ROOT / "datasets/benchmarks/ragtruth/runs/week06-day04/validation"
DEFAULT_EMBEDDING_MODEL = _REPO_ROOT / "data/models/embedding/bge-m3"
DEFAULT_NLI_MODEL = _REPO_ROOT / "data/models/nli/nli-deberta-v3-base"
NLI_FEATURE_NAMES = ("max_contradiction", "max_entailment", "max_neutral")
EXPECTED_NLI_LABELS = {0: "contradiction", 1: "entailment", 2: "neutral"}
NLI_BATCH_SIZE = 8
NLI_FALLBACK_BATCH_SIZE = 4
NLI_MAX_LENGTH = 512
GPU_PEAK_BUDGET_BYTES = 4 * 1024**3
BOOTSTRAP_RESAMPLES = 10_000


class MemoryBudgetExceeded(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Week 6 Day 4 NLI validation experiment")
    parser.add_argument("--experiment-id", default=EXPERIMENT_ID)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--nli-model", type=Path, default=DEFAULT_NLI_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--embedding-batch-size", type=int, default=EMBEDDING_BATCH_SIZE)
    parser.add_argument("--nli-batch-size", type=int, default=NLI_BATCH_SIZE)
    parser.add_argument("--force-dense", action="store_true")
    parser.add_argument("--force-nli", action="store_true")
    return parser


def validate_registered_experiment(experiment_id: str) -> tuple[int, str, str]:
    if experiment_id != EXPERIMENT_ID:
        raise ValueError(f"this runner only supports experiment {EXPERIMENT_ID}")
    experiment = load_experiment_registry().get(experiment_id)
    if experiment.status != ExperimentStatus.READY:
        raise ValueError(f"experiment is not ready: {experiment.status.value}")
    declared = tuple(
        require_optimization_split(item.value).value for item in experiment.optimization_splits
    )
    if (
        experiment.task.value != "hallucination_detection"
        or declared != OPTIMIZATION_SPLITS
        or experiment.test_access != "forbidden"
    ):
        raise ValueError("registered task/split/test contract is invalid")
    dataset = experiment.revisions.datasets[0]
    model = experiment.revisions.models[0]
    if len(experiment.random_seeds) != 1 or dataset.sha256 is None:
        raise ValueError("registered seed or dataset identity is incomplete")
    if (
        dataset.name != "ragtruth-train-only"
        or model.name != "cross-encoder/nli-deberta-v3-base"
        or model.revision is None
        or model.sha256 is None
    ):
        raise ValueError("registered Day 4 identities are incomplete")
    return experiment.random_seeds[0], dataset.sha256, model.revision


def verify_derived_dataset(
    dataset_root: Path, expected_manifest_hash: str
) -> tuple[dict[str, Any], tuple[RagTruthExample, ...]]:
    manifest_path = dataset_root / "manifest.json"
    if hash_file(manifest_path) != expected_manifest_hash:
        raise ValueError("derived manifest differs from the registered hash")
    payload = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    boundary = payload.get("boundary")
    if (
        payload.get("dataset_id") != "ragtruth-train-only"
        or payload.get("lifecycle") != "frozen"
        or not isinstance(boundary, dict)
        or boundary.get("selected_split") != "train"
        or boundary.get("excluded_rows_decoded") is not False
    ):
        raise ValueError("derived dataset boundary is invalid")
    files = cast(dict[str, str], payload["files"])
    if set(files) != {"response.jsonl", "source_info.jsonl"}:
        raise ValueError("derived manifest must contain exactly two data files")
    for name, expected_hash in files.items():
        if hash_file(dataset_root / name) != expected_hash:
            raise ValueError(f"derived file hash changed: {name}")
    adapter = RagTruthAdapter(dataset_root)
    counts = adapter.validate(("train",))
    expected_counts = cast(dict[str, int], payload["split_counts"]["train"])
    if counts["train"] != expected_counts or counts["all"] != expected_counts:
        raise ValueError("derived counts differ from the frozen manifest")
    examples = tuple(adapter.iter_examples("train"))
    if len(examples) != expected_counts["responses"] or any(x.split != "train" for x in examples):
        raise ValueError("non-train data reached the optimization dataset")
    return payload, examples


def verify_nli_model(model_root: Path, revision: str) -> dict[str, Any]:
    registered = load_experiment_registry().get(EXPERIMENT_ID).revisions.models[0]
    if hash_file(model_root / "model.safetensors") != registered.sha256:
        raise ValueError("NLI weight hash differs from the registered identity")
    metadata = model_root / ".cache/huggingface/download/model.safetensors.metadata"
    lines = metadata.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != revision:
        raise ValueError("NLI download metadata differs from the registered revision")
    return {
        "repo": registered.name,
        "revision": revision,
        "weight_sha256": registered.sha256,
        "config_sha256": hash_file(model_root / "config.json"),
        "format": "safetensors",
    }


def stratified_source_split(
    source_tasks: Mapping[str, str], *, seed: int
) -> dict[str, frozenset[str]]:
    by_task: defaultdict[str, list[str]] = defaultdict(list)
    for source_id, task in source_tasks.items():
        by_task[task].append(source_id)
    result: dict[str, set[str]] = {"fit": set(), "calibration": set(), "validation": set()}
    for task in sorted(by_task):
        members = sorted(
            by_task[task],
            key=lambda source_id: (
                hashlib.sha256(f"{seed}\0{task}\0{source_id}".encode()).digest(),
                source_id,
            ),
        )
        if len(members) < 3:
            raise ValueError(f"task group is too small for three-way splitting: {task}")
        calibration_count = max(1, round(len(members) * 0.2))
        validation_count = max(1, round(len(members) * 0.2))
        fit_count = len(members) - calibration_count - validation_count
        if fit_count < 1:
            raise ValueError(f"task group has no fit source: {task}")
        result["fit"].update(members[:fit_count])
        result["calibration"].update(members[fit_count : fit_count + calibration_count])
        result["validation"].update(members[fit_count + calibration_count :])
    union = set().union(*result.values())
    if union != set(source_tasks) or sum(map(len, result.values())) != len(union):
        raise ValueError("source split is incomplete or overlapping")
    return {name: frozenset(values) for name, values in result.items()}


def aggregate_nli_pairs(
    record_count: int,
    record_positions: Sequence[int],
    probabilities: NDArray[np.float64],
) -> NDArray[np.float64]:
    if probabilities.shape != (len(record_positions), 3):
        raise ValueError("NLI probabilities must have shape (pairs, 3)")
    result = np.full((record_count, 3), -np.inf, dtype=np.float64)
    for pair_index, record_index in enumerate(record_positions):
        if not 0 <= record_index < record_count:
            raise ValueError("NLI pair references an invalid sentence")
        result[record_index] = np.maximum(result[record_index], probabilities[pair_index])
    if not np.all(np.isfinite(result)):
        raise ValueError("every sentence must have at least one NLI pair")
    return result


def _nli_cache_key(
    records: Sequence[SentenceRecord], manifest: Mapping[str, Any], identity: Mapping[str, Any]
) -> str:
    payload = {
        "dataset_files": manifest["files"],
        "model": identity,
        "chunk_chars": CONTEXT_CHUNK_CHARS,
        "chunk_overlap": CONTEXT_OVERLAP_CHARS,
        "max_length": NLI_MAX_LENGTH,
        "labels": EXPECTED_NLI_LABELS,
        "sentence_count": len(records),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def load_or_compute_nli_features(
    *,
    records: Sequence[SentenceRecord],
    source_contexts: Mapping[str, str],
    manifest: Mapping[str, Any],
    model_root: Path,
    identity: Mapping[str, Any],
    output: Path,
    device_preference: str,
    batch_size: int,
    force: bool,
) -> tuple[NDArray[np.float64], dict[str, Any]]:
    cache_key = _nli_cache_key(records, manifest, identity)
    cache_path = output / "nli-features.npz"
    if cache_path.exists() and not force:
        with np.load(cache_path, allow_pickle=False) as cached:
            stored_key = str(cached["cache_key"].item())
            features = np.asarray(cached["features"], dtype=np.float64)
            metadata = {
                "cache": "hit",
                "cache_key": cache_key,
                "batch_size": int(cached["batch_size"].item()),
                "pair_count": int(cached["pair_count"].item()),
                "inference_seconds": float(cached["inference_seconds"].item()),
                "peak_allocated_bytes": int(cached["peak_allocated_bytes"].item()),
            }
        if stored_key == cache_key and features.shape == (len(records), 3):
            return features, {**metadata, "cache_sha256": hash_file(cache_path)}

    device = resolve_device(device_preference)
    if device != "cuda":
        raise RuntimeError("the approved Day 4 execution requires CUDA")
    tokenizer: Any = AutoTokenizer.from_pretrained(
        str(model_root), local_files_only=True, trust_remote_code=False
    )
    load_started = time.perf_counter()
    model: Any = AutoModelForSequenceClassification.from_pretrained(
        str(model_root),
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
        dtype=torch.float16,
    ).to(device)
    model.eval()
    labels = {int(key): str(value).lower() for key, value in model.config.id2label.items()}
    if labels != EXPECTED_NLI_LABELS:
        raise ValueError(f"unexpected NLI label order: {labels}")
    load_seconds = time.perf_counter() - load_started
    chunks = {
        source_id: context_chunks(
            text, max_chars=CONTEXT_CHUNK_CHARS, overlap_chars=CONTEXT_OVERLAP_CHARS
        )
        for source_id, text in source_contexts.items()
    }
    pair_count = sum(len(chunks[record.source_id]) for record in records)
    features = np.full((len(records), 3), -np.inf, dtype=np.float64)
    premises: list[str] = []
    hypotheses: list[str] = []
    positions: list[int] = []
    completed = 0
    torch.cuda.reset_peak_memory_stats()
    inference_started = time.perf_counter()

    def flush() -> None:
        nonlocal completed
        if not positions:
            return
        encoded = tokenizer(
            premises,
            hypotheses,
            padding=True,
            truncation="only_first",
            max_length=NLI_MAX_LENGTH,
            return_tensors="pt",
        )
        encoded = {name: value.to(device) for name, value in encoded.items()}
        with torch.inference_mode():
            probabilities = torch.softmax(model(**encoded).logits.float(), dim=-1).cpu().numpy()
        for pair_index, record_index in enumerate(positions):
            features[record_index] = np.maximum(features[record_index], probabilities[pair_index])
        completed += len(positions)
        premises.clear()
        hypotheses.clear()
        positions.clear()
        if completed % (batch_size * 500) == 0 or completed == pair_count:
            print(f"nli_progress={completed}/{pair_count}", flush=True)

    for record_index, record in enumerate(records):
        for chunk in chunks[record.source_id]:
            premises.append(chunk)
            hypotheses.append(record.span.text)
            positions.append(record_index)
            if len(positions) == batch_size:
                flush()
    flush()
    torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - inference_started
    peak_allocated = int(torch.cuda.max_memory_allocated())
    if peak_allocated > GPU_PEAK_BUDGET_BYTES:
        raise MemoryBudgetExceeded(f"NLI peak {peak_allocated} exceeds {GPU_PEAK_BUDGET_BYTES}")
    if completed != pair_count or not np.all(np.isfinite(features)):
        raise ValueError("NLI feature computation is incomplete")
    temporary = cache_path.with_suffix(".tmp.npz")
    np.savez_compressed(
        temporary,
        cache_key=np.asarray(cache_key),
        features=features,
        batch_size=np.asarray(batch_size),
        pair_count=np.asarray(pair_count),
        inference_seconds=np.asarray(inference_seconds),
        peak_allocated_bytes=np.asarray(peak_allocated),
    )
    temporary.replace(cache_path)
    metadata = {
        "cache": "miss",
        "cache_key": cache_key,
        "cache_sha256": hash_file(cache_path),
        "batch_size": batch_size,
        "pair_count": pair_count,
        "model_load_seconds": load_seconds,
        "inference_seconds": inference_seconds,
        "peak_allocated_bytes": peak_allocated,
        "gpu_budget_bytes": GPU_PEAK_BUDGET_BYTES,
    }
    gc.collect()
    torch.cuda.empty_cache()
    return features, metadata


def metric_deltas(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, float]:
    return {
        "span_char_f1": float(candidate["span_char"]["f1"]) - float(baseline["span_char"]["f1"]),
        "response_auprc": float(candidate["response"]["auprc"])
        - float(baseline["response"]["auprc"]),
        "response_recall": float(candidate["response"]["recall"])
        - float(baseline["response"]["recall"]),
    }


def _char_counts(
    scores: NDArray[np.float64],
    threshold: float,
    examples: Sequence[RagTruthExample],
    records: Sequence[SentenceRecord],
    record_indices: Sequence[Sequence[int]],
    selected: Sequence[int],
) -> NDArray[np.int64]:
    counts = np.zeros(4, dtype=np.int64)
    for index in selected:
        expected = char_labels(len(examples[index].response), examples[index].labels)
        spans = (
            records[position].span
            for position in record_indices[index]
            if scores[position] >= threshold
        )
        predicted = predicted_char_labels(len(examples[index].response), spans)
        for label, prediction in zip(expected, predicted, strict=True):
            bucket = (
                0 if label and prediction else 1 if not label and prediction else 2 if label else 3
            )
            counts[bucket] += 1
    return counts


def source_cluster_bootstrap(
    *,
    baseline_scores: NDArray[np.float64],
    candidate_scores: NDArray[np.float64],
    baseline_threshold: float,
    candidate_threshold: float,
    examples: Sequence[RagTruthExample],
    records: Sequence[SentenceRecord],
    record_indices: Sequence[Sequence[int]],
    validation_examples: Sequence[int],
    seed: int,
) -> dict[str, Any]:
    grouped: defaultdict[str, list[int]] = defaultdict(list)
    for index in validation_examples:
        grouped[examples[index].source_id].append(index)
    source_ids = sorted(grouped)
    baseline_counts = np.vstack(
        [
            _char_counts(
                baseline_scores,
                baseline_threshold,
                examples,
                records,
                record_indices,
                grouped[source_id],
            )
            for source_id in source_ids
        ]
    )
    candidate_counts = np.vstack(
        [
            _char_counts(
                candidate_scores,
                candidate_threshold,
                examples,
                records,
                record_indices,
                grouped[source_id],
            )
            for source_id in source_ids
        ]
    )
    generator = np.random.default_rng(seed)
    selections = generator.integers(0, len(source_ids), size=(BOOTSTRAP_RESAMPLES, len(source_ids)))

    def f1(sampled: NDArray[np.int64]) -> NDArray[np.float64]:
        values = np.sum(sampled, axis=1)
        denominator = 2 * values[:, 0] + values[:, 1] + values[:, 2]
        return np.asarray(
            np.divide(
                2 * values[:, 0],
                denominator,
                out=np.zeros(len(values), dtype=np.float64),
                where=denominator != 0,
            ),
            dtype=np.float64,
        )

    deltas = f1(candidate_counts[selections]) - f1(baseline_counts[selections])
    return {
        "unit": "source_id",
        "metric": "micro span char F1 delta",
        "seed": seed,
        "resamples": BOOTSTRAP_RESAMPLES,
        "source_count": len(source_ids),
        "ci95": [float(value) for value in np.quantile(deltas, [0.025, 0.975])],
        "positive_fraction": float(np.mean(deltas > 0.0)),
    }


def _example_f1(
    index: int,
    scores: NDArray[np.float64],
    threshold: float,
    examples: Sequence[RagTruthExample],
    records: Sequence[SentenceRecord],
    record_indices: Sequence[Sequence[int]],
) -> float:
    counts = _char_counts(scores, threshold, examples, records, record_indices, (index,))
    return metrics_from_confusion(counts.tolist()).f1


def build_slice_summary(
    *,
    examples: Sequence[RagTruthExample],
    records: Sequence[SentenceRecord],
    record_indices: Sequence[Sequence[int]],
    validation_examples: Sequence[int],
    source_contexts: Mapping[str, str],
    baseline_scores: NDArray[np.float64],
    candidate_scores: NDArray[np.float64],
    baseline_thresholds: Thresholds,
    candidate_thresholds: Thresholds,
) -> dict[str, Any]:
    evidence_counts = {
        source_id: len(
            context_chunks(
                text,
                max_chars=CONTEXT_CHUNK_CHARS,
                overlap_chars=CONTEXT_OVERLAP_CHARS,
            )
        )
        for source_id, text in source_contexts.items()
    }
    observations: list[SliceObservation] = []
    for index in validation_examples:
        baseline_f1 = _example_f1(
            index,
            baseline_scores,
            baseline_thresholds.span,
            examples,
            records,
            record_indices,
        )
        candidate_f1 = _example_f1(
            index,
            candidate_scores,
            candidate_thresholds.span,
            examples,
            records,
            record_indices,
        )
        delta = candidate_f1 - baseline_f1
        error_type = (
            "candidate-better" if delta > 1e-12 else "candidate-worse" if delta < -1e-12 else "tie"
        )
        observations.append(
            SliceObservation(
                split=OptimizationSplit.VALIDATION,
                domain=examples[index].task_type,
                class_label=(
                    SliceClass.POSITIVE
                    if examples[index].has_hallucination
                    else SliceClass.NEGATIVE
                ),
                text_length_chars=len(examples[index].response),
                evidence_count=evidence_counts[examples[index].source_id],
                error_types=(error_type,),
                metrics={
                    "baseline_span_char_f1": baseline_f1,
                    "candidate_span_char_f1": candidate_f1,
                    "span_char_f1_delta": delta,
                },
            )
        )
    return {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "split": "validation",
        "contains_sample_ids_or_text": False,
        "dimensions": ["domain", "class", "length", "evidence_count", "error_type"],
        "aggregates": [item.model_dump(mode="json") for item in aggregate_slices(observations)],
    }


def _clean_dense_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = dict(metadata)
    model = cleaned.get("model")
    if isinstance(model, dict):
        cleaned["model"] = {key: value for key, value in model.items() if key != "path"}
    return cleaned


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.embedding_batch_size < 1 or arguments.nli_batch_size not in {4, 8}:
        raise ValueError("embedding batch must be positive and NLI batch must be 4 or 8")
    seed, manifest_hash, model_revision = validate_registered_experiment(arguments.experiment_id)
    started = time.perf_counter()
    process = psutil.Process()
    dataset_root = arguments.dataset_root.resolve()
    manifest, examples = verify_derived_dataset(dataset_root, manifest_hash)
    source_contexts = unique_source_contexts(examples)
    records, record_indices = build_sentence_records(examples)

    source_tasks: dict[str, str] = {}
    for example in examples:
        existing = source_tasks.setdefault(example.source_id, example.task_type)
        if existing != example.task_type:
            raise ValueError("a RAGTruth source cannot cross task groups")
    source_splits = stratified_source_split(source_tasks, seed=seed)
    example_splits = {
        name: tuple(
            index for index, example in enumerate(examples) if example.source_id in source_ids
        )
        for name, source_ids in source_splits.items()
    }

    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    train_counts = cast(dict[str, int], manifest["split_counts"]["train"])
    dense_manifest = RagTruthManifest.model_validate(
        {
            "schema_version": "1.0",
            "dataset_id": "ragtruth",
            "lifecycle": "frozen",
            "source_url": "https://github.com/ParticleMedia/RAGTruth",
            "source_revision": manifest["parent"]["source_revision"],
            "files": manifest["files"],
            "file_bytes": manifest["file_bytes"],
            "split_counts": {"all": train_counts, "train": train_counts},
        }
    )
    dense_started = time.perf_counter()
    dense_support, dense_metadata = load_or_compute_dense_support(
        records=records,
        source_contexts=source_contexts,
        model_path=arguments.embedding_model.resolve(),
        output=output,
        device_preference=arguments.device,
        batch_size=arguments.embedding_batch_size,
        manifest=dense_manifest,
        force=arguments.force_dense,
    )
    dense_seconds = time.perf_counter() - dense_started
    gc.collect()
    torch.cuda.empty_cache()

    nli_identity = verify_nli_model(arguments.nli_model.resolve(), model_revision)
    selected_batch = arguments.nli_batch_size
    try:
        nli_features, nli_metadata = load_or_compute_nli_features(
            records=records,
            source_contexts=source_contexts,
            manifest=manifest,
            model_root=arguments.nli_model.resolve(),
            identity=nli_identity,
            output=output,
            device_preference=arguments.device,
            batch_size=selected_batch,
            force=arguments.force_nli,
        )
    except (torch.cuda.OutOfMemoryError, MemoryBudgetExceeded):
        if selected_batch != NLI_BATCH_SIZE:
            raise
        print("nli_batch_8_failed_retrying_batch_4", flush=True)
        gc.collect()
        torch.cuda.empty_cache()
        selected_batch = NLI_FALLBACK_BATCH_SIZE
        nli_features, nli_metadata = load_or_compute_nli_features(
            records=records,
            source_contexts=source_contexts,
            manifest=manifest,
            model_root=arguments.nli_model.resolve(),
            identity=nli_identity,
            output=output,
            device_preference=arguments.device,
            batch_size=selected_batch,
            force=True,
        )

    lexical = np.asarray([record.lexical_features for record in records], dtype=np.float64)
    baseline_features = np.column_stack((lexical, dense_support))
    candidate_features = np.column_stack((baseline_features, nli_features))
    labels = np.asarray([record.label for record in records], dtype=np.int64)
    fit_indices = flatten_record_indices(record_indices, example_splits["fit"])

    def fit_scores(features: NDArray[np.float64]) -> tuple[NDArray[np.float64], Any, float]:
        model = LogisticRegression(
            class_weight="balanced", max_iter=1000, random_state=seed, solver="lbfgs"
        )
        fit_started = time.perf_counter()
        model.fit(features[fit_indices], labels[fit_indices])
        seconds = time.perf_counter() - fit_started
        return np.asarray(model.predict_proba(features)[:, 1], dtype=np.float64), model, seconds

    baseline_scores, baseline_model, baseline_fit_seconds = fit_scores(baseline_features)
    candidate_scores, candidate_model, candidate_fit_seconds = fit_scores(candidate_features)
    lexical_support = 0.30 * lexical[:, 0] + 0.50 * lexical[:, 1] + 0.20 * lexical[:, 2]
    method_scores = {
        "historical_lexical_coverage": np.clip(1.0 - lexical_support, 0.0, 1.0),
        "baseline_lexical_dense_logistic": baseline_scores,
        "candidate_lexical_dense_logistic_plus_nli": candidate_scores,
    }
    thresholds = {
        name: tune_thresholds(
            scores=scores,
            examples=examples,
            records=records,
            record_indices=record_indices,
            selected_examples=example_splits["calibration"],
        )
        for name, scores in method_scores.items()
    }
    validation_results = {
        name: evaluate_method(
            scores=scores,
            thresholds=thresholds[name],
            examples=examples,
            records=records,
            record_indices=record_indices,
            selected_examples=example_splits["validation"],
        )
        for name, scores in method_scores.items()
    }
    baseline = validation_results["baseline_lexical_dense_logistic"]
    candidate = validation_results["candidate_lexical_dense_logistic_plus_nli"]
    deltas = metric_deltas(baseline, candidate)
    incremental_latency_ms = float(nli_metadata["inference_seconds"]) * 1000 / len(examples)
    gates = {
        "span_char_f1_improved": deltas["span_char_f1"] > 0.0,
        "response_auprc_not_regressed": deltas["response_auprc"] >= 0.0,
        "response_recall_not_regressed": deltas["response_recall"] >= 0.0,
        "incremental_mean_latency_within_250ms": incremental_latency_ms <= 250.0,
    }
    bootstrap = source_cluster_bootstrap(
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        baseline_threshold=thresholds["baseline_lexical_dense_logistic"].span,
        candidate_threshold=thresholds["candidate_lexical_dense_logistic_plus_nli"].span,
        examples=examples,
        records=records,
        record_indices=record_indices,
        validation_examples=example_splits["validation"],
        seed=seed,
    )
    stable_gain = float(bootstrap["ci95"][0]) > 0.0
    all_metric_gates = all(gates.values())
    decision = "promote" if all_metric_gates and stable_gain else "provisional"
    if not all_metric_gates:
        decision = "reject"

    slice_payload = build_slice_summary(
        examples=examples,
        records=records,
        record_indices=record_indices,
        validation_examples=example_splits["validation"],
        source_contexts=source_contexts,
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        baseline_thresholds=thresholds["baseline_lexical_dense_logistic"],
        candidate_thresholds=thresholds["candidate_lexical_dense_logistic_plus_nli"],
    )
    slice_path = output / "slice-summary.json"
    write_json_atomic(slice_path, slice_payload)

    embedding_identity = model_identity(arguments.embedding_model.resolve())
    embedding_identity.pop("path", None)
    baseline_feature_names = tuple(FEATURE_NAMES)
    summary = {
        "schema_version": "1.0",
        "experiment_id": arguments.experiment_id,
        "benchmark": "ragtruth-train-only",
        "decision_split": "validation",
        "test_access": "forbidden_and_not_read",
        "protocol": {
            "derived_manifest_sha256": manifest_hash,
            "derived_files": manifest["files"],
            "parent_revision": manifest["parent"]["source_revision"],
            "source_grouping": "source_id + task_type",
            "split_ratio": {"fit": 0.6, "calibration": 0.2, "validation": 0.2},
            "seed": seed,
            "sources": {name: len(values) for name, values in source_splits.items()},
            "responses": {name: len(values) for name, values in example_splits.items()},
            "sentence_count": len(records),
            "official_test_accesses": 0,
            "prediction_artifacts_written": 0,
            "external_api_calls": 0,
        },
        "features": {
            "baseline": list(baseline_feature_names),
            "candidate_addition": list(NLI_FEATURE_NAMES),
            "embedding_model": embedding_identity,
            "nli_model": nli_identity,
            "dense": {**_clean_dense_metadata(dense_metadata), "wall_seconds": dense_seconds},
            "nli": nli_metadata,
        },
        "methods": {
            name: {"thresholds": asdict(thresholds[name]), "validation": result}
            for name, result in validation_results.items()
        },
        "models": {
            "baseline": {
                "algorithm": "LogisticRegression",
                "class_weight": "balanced",
                "feature_names": list(baseline_feature_names),
                "coefficients": [float(value) for value in baseline_model.coef_[0]],
                "intercept": float(baseline_model.intercept_[0]),
                "fit_seconds": baseline_fit_seconds,
            },
            "candidate": {
                "algorithm": "LogisticRegression",
                "class_weight": "balanced",
                "feature_names": [*baseline_feature_names, *NLI_FEATURE_NAMES],
                "coefficients": [float(value) for value in candidate_model.coef_[0]],
                "intercept": float(candidate_model.intercept_[0]),
                "fit_seconds": candidate_fit_seconds,
            },
        },
        "deltas": deltas,
        "latency": {"incremental_nli_mean_ms_per_response": incremental_latency_ms},
        "gates": {
            **gates,
            "all_metric_gates_passed": all_metric_gates,
            "bootstrap_ci_lower_above_zero": stable_gain,
        },
        "statistics": {"source_clustered_bootstrap": bootstrap},
        "decision": decision,
        "runtime": {
            "wall_seconds": time.perf_counter() - started,
            "peak_working_set_bytes": process.memory_info().peak_wset,
            "hardware": hardware_info(),
        },
        "privacy": {
            "contains_sample_ids": False,
            "contains_source_or_response_text": False,
            "contains_gold_spans": False,
            "contains_per_sample_scores": False,
        },
        "artifacts": {
            "slice_summary": slice_path.name,
            "slice_summary_sha256": hash_file(slice_path),
            "runner_sha256": hash_file(Path(__file__)),
        },
    }
    summary_path = output / "summary.json"
    write_json_atomic(summary_path, summary)
    print(
        json.dumps(
            {
                "baseline": baseline,
                "candidate": candidate,
                "deltas": deltas,
                "gates": summary["gates"],
                "bootstrap": bootstrap,
                "decision": decision,
                "summary": str(summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    raise SystemExit(main())
