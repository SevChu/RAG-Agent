from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import numpy as np
import psutil  # type: ignore[import-untyped]
import torch
from numpy.typing import NDArray

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    ExperimentStatus,
    RagTruthAdapter,
    RagTruthExample,
    RagTruthManifest,
    hash_file,
    load_baseline_profiles,
    load_experiment_registry,
)
from app.evaluation.run_store import write_json_atomic  # noqa: E402
from scripts.run_hallucination_benchmark import (  # noqa: E402
    EMBEDDING_BATCH_SIZE,
    FEATURE_NAMES,
    Thresholds,
    build_sentence_records,
    evaluate_method,
    hardware_info,
    load_or_compute_dense_support,
    model_identity,
    unique_source_contexts,
)
from scripts.run_ragtruth_nli_experiment import (  # noqa: E402
    EXPERIMENT_ID,
    NLI_BATCH_SIZE,
    NLI_FALLBACK_BATCH_SIZE,
    NLI_FEATURE_NAMES,
    MemoryBudgetExceeded,
    _clean_dense_metadata,
    build_slice_summary,
    load_or_compute_nli_features,
    metric_deltas,
    source_cluster_bootstrap,
    verify_nli_model,
)

FINAL_RUN_ID = "w6-d5-ragtruth-nli-final-test"
VALIDATION_SUMMARY_SHA256 = "babefd7f3eef7583dc37e4b0c1bfb2319ba688ce7c706ea6e0f38467e32c4143"
DEFAULT_DATASET = _BACKEND_ROOT / "datasets/benchmarks/ragtruth/derived/test-only"
DEFAULT_VALIDATION_SUMMARY = (
    _BACKEND_ROOT / "datasets/benchmarks/ragtruth/runs/week06-day04/validation/summary.json"
)
DEFAULT_OUTPUT = _BACKEND_ROOT / "datasets/benchmarks/ragtruth/runs/week06-day05/final-test"
DEFAULT_EMBEDDING_MODEL = _REPO_ROOT / "data/models/embedding/bge-m3"
DEFAULT_NLI_MODEL = _REPO_ROOT / "data/models/nli/nli-deberta-v3-base"
APPROVAL_DOC = _REPO_ROOT / "docs/deliverables/week-06-day-05-approval.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the approved Week 6 Day 5 frozen NLI candidate on RAGTruth test"
    )
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--dataset-manifest-sha256", required=True)
    parser.add_argument("--validation-summary", type=Path, default=DEFAULT_VALIDATION_SUMMARY)
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--nli-model", type=Path, default=DEFAULT_NLI_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--embedding-batch-size", type=int, default=EMBEDDING_BATCH_SIZE)
    parser.add_argument("--nli-batch-size", type=int, default=NLI_BATCH_SIZE)
    parser.add_argument("--force-dense", action="store_true")
    parser.add_argument("--force-nli", action="store_true")
    return parser


def _verify_approval() -> str:
    text = APPROVAL_DOC.read_text(encoding="utf-8")
    required = (
        "审批结果：用户于 2026-09-04 批准 A/B/C",
        "Day 5 只执行冻结的 Day 4 NLI Span 候选一次性 RAGTruth test",
    )
    if any(item not in text for item in required):
        raise ValueError("Day 5 A/B/C approval record is incomplete")
    return hash_file(APPROVAL_DOC)


def verify_test_dataset(
    dataset_root: Path, expected_manifest_hash: str
) -> tuple[dict[str, Any], tuple[RagTruthExample, ...]]:
    manifest_path = dataset_root / "manifest.json"
    if hash_file(manifest_path) != expected_manifest_hash:
        raise ValueError("test-only manifest differs from the command-line frozen hash")
    payload = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    boundary = payload.get("boundary")
    if (
        payload.get("dataset_id") != "ragtruth-test-only"
        or payload.get("lifecycle") != "frozen"
        or payload.get("derivation") != "ragtruth-stream-filter-test-v1"
        or not isinstance(boundary, dict)
        or boundary.get("selected_split") != "test"
        or boundary.get("excluded_rows_decoded") is not False
        or boundary.get("sample_payloads_recorded") is not False
    ):
        raise ValueError("test-only dataset boundary is invalid")
    files = cast(dict[str, str], payload["files"])
    if set(files) != {"response.jsonl", "source_info.jsonl"}:
        raise ValueError("test-only manifest must contain exactly two data files")
    for name, expected_hash in files.items():
        if hash_file(dataset_root / name) != expected_hash:
            raise ValueError(f"test-only file hash changed: {name}")
    adapter = RagTruthAdapter(dataset_root)
    counts = adapter.validate(("test",))
    expected_counts = cast(dict[str, int], payload["split_counts"]["test"])
    if counts["test"] != expected_counts or counts["all"] != expected_counts:
        raise ValueError("test-only counts differ from the frozen manifest")
    examples = tuple(adapter.iter_examples("test"))
    if len(examples) != expected_counts["responses"] or any(x.split != "test" for x in examples):
        raise ValueError("non-test data reached the final evaluation")
    return payload, examples


def load_frozen_validation(path: Path) -> dict[str, Any]:
    if hash_file(path) != VALIDATION_SUMMARY_SHA256:
        raise ValueError("validation summary differs from the approved frozen identity")
    payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    if (
        payload.get("experiment_id") != EXPERIMENT_ID
        or payload.get("decision") != "promote"
        or payload.get("test_access") != "forbidden_and_not_read"
        or not payload.get("gates", {}).get("all_metric_gates_passed")
    ):
        raise ValueError("validation summary is not an approved promoted candidate")
    baseline = payload["models"]["baseline"]
    candidate = payload["models"]["candidate"]
    methods = payload["methods"]
    if tuple(baseline["feature_names"]) != tuple(FEATURE_NAMES):
        raise ValueError("frozen baseline feature order changed")
    if tuple(candidate["feature_names"]) != (*FEATURE_NAMES, *NLI_FEATURE_NAMES):
        raise ValueError("frozen candidate feature order changed")
    expected_thresholds = {
        "baseline_lexical_dense_logistic": Thresholds(response=0.57, span=0.67),
        "candidate_lexical_dense_logistic_plus_nli": Thresholds(response=0.585, span=0.71),
    }
    for name, expected in expected_thresholds.items():
        observed = methods[name]["thresholds"]
        if not (
            np.isclose(float(observed["response"]), expected.response)
            and np.isclose(float(observed["span"]), expected.span)
        ):
            raise ValueError(f"frozen thresholds changed: {name}")
    return payload


def frozen_logistic_scores(
    features: NDArray[np.float64], model_payload: dict[str, Any]
) -> NDArray[np.float64]:
    coefficients = np.asarray(model_payload["coefficients"], dtype=np.float64)
    if coefficients.shape != (features.shape[1],):
        raise ValueError("frozen coefficient count differs from the feature matrix")
    logits = features @ coefficients + float(model_payload["intercept"])
    scores = np.empty_like(logits, dtype=np.float64)
    positive = logits >= 0
    scores[positive] = 1.0 / (1.0 + np.exp(-logits[positive]))
    exp_values = np.exp(logits[~positive])
    scores[~positive] = exp_values / (1.0 + exp_values)
    return scores


def frozen_thresholds(validation: dict[str, Any]) -> dict[str, Thresholds]:
    lexical = load_baseline_profiles().get("ragtruth-lexical-hallucination")
    return {
        "historical_lexical_coverage": Thresholds(
            response=float(lexical.parameters["response_threshold"]),
            span=float(lexical.parameters["span_threshold"]),
        ),
        **{
            name: Thresholds(
                response=float(payload["thresholds"]["response"]),
                span=float(payload["thresholds"]["span"]),
            )
            for name, payload in validation["methods"].items()
            if name
            in {
                "baseline_lexical_dense_logistic",
                "candidate_lexical_dense_logistic_plus_nli",
            }
        },
    }


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.embedding_batch_size < 1 or arguments.nli_batch_size not in {4, 8}:
        raise ValueError("embedding batch must be positive and NLI batch must be 4 or 8")
    if len(arguments.dataset_manifest_sha256) != 64:
        raise ValueError("dataset manifest SHA-256 must contain 64 hex characters")

    approval_hash = _verify_approval()
    validation_path = arguments.validation_summary.resolve()
    validation = load_frozen_validation(validation_path)
    experiment = load_experiment_registry().get(EXPERIMENT_ID)
    if experiment.status != ExperimentStatus.READY or experiment.test_access != "forbidden":
        raise ValueError("optimization experiment registry no longer preserves the test boundary")

    output = arguments.output.resolve()
    summary_path = output / "summary.json"
    if summary_path.exists():
        raise FileExistsError("refusing to repeat a completed final test")
    output.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    process = psutil.Process()
    dataset_root = arguments.dataset_root.resolve()
    manifest, examples = verify_test_dataset(
        dataset_root, arguments.dataset_manifest_sha256.lower()
    )
    source_contexts = unique_source_contexts(examples)
    records, record_indices = build_sentence_records(examples)
    selected_examples = tuple(range(len(examples)))
    test_counts = cast(dict[str, int], manifest["split_counts"]["test"])
    dense_manifest = RagTruthManifest.model_validate(
        {
            "schema_version": "1.0",
            "dataset_id": "ragtruth",
            "lifecycle": "frozen",
            "source_url": "https://github.com/ParticleMedia/RAGTruth",
            "source_revision": manifest["parent"]["source_revision"],
            "files": manifest["files"],
            "file_bytes": manifest["file_bytes"],
            "split_counts": {"all": test_counts, "test": test_counts},
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

    model_revision = str(validation["features"]["nli_model"]["revision"])
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
    baseline_scores = frozen_logistic_scores(baseline_features, validation["models"]["baseline"])
    candidate_scores = frozen_logistic_scores(candidate_features, validation["models"]["candidate"])
    lexical_support = 0.30 * lexical[:, 0] + 0.50 * lexical[:, 1] + 0.20 * lexical[:, 2]
    method_scores = {
        "historical_lexical_coverage": np.clip(1.0 - lexical_support, 0.0, 1.0),
        "baseline_lexical_dense_logistic": baseline_scores,
        "candidate_lexical_dense_logistic_plus_nli": candidate_scores,
    }
    thresholds = frozen_thresholds(validation)
    results = {
        name: evaluate_method(
            scores=scores,
            thresholds=thresholds[name],
            examples=examples,
            records=records,
            record_indices=record_indices,
            selected_examples=selected_examples,
        )
        for name, scores in method_scores.items()
    }
    baseline = results["baseline_lexical_dense_logistic"]
    candidate = results["candidate_lexical_dense_logistic_plus_nli"]
    deltas = metric_deltas(baseline, candidate)
    incremental_latency_ms = float(nli_metadata["inference_seconds"]) * 1000 / len(examples)
    gates = {
        "span_char_f1_improved": deltas["span_char_f1"] > 0.0,
        "response_auprc_not_regressed": deltas["response_auprc"] >= 0.0,
        "response_recall_not_regressed": deltas["response_recall"] >= 0.0,
        "incremental_mean_latency_within_250ms": incremental_latency_ms <= 250.0,
    }
    all_gates = all(gates.values())
    bootstrap = source_cluster_bootstrap(
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        baseline_threshold=thresholds["baseline_lexical_dense_logistic"].span,
        candidate_threshold=thresholds["candidate_lexical_dense_logistic_plus_nli"].span,
        examples=examples,
        records=records,
        record_indices=record_indices,
        validation_examples=selected_examples,
        seed=42,
    )
    slice_payload = build_slice_summary(
        examples=examples,
        records=records,
        record_indices=record_indices,
        validation_examples=selected_examples,
        source_contexts=source_contexts,
        baseline_scores=baseline_scores,
        candidate_scores=candidate_scores,
        baseline_thresholds=thresholds["baseline_lexical_dense_logistic"],
        candidate_thresholds=thresholds["candidate_lexical_dense_logistic_plus_nli"],
    )
    slice_payload["experiment_id"] = FINAL_RUN_ID
    slice_payload["split"] = "test"
    slice_path = output / "slice-summary.json"
    write_json_atomic(slice_path, slice_payload)

    embedding_identity = model_identity(arguments.embedding_model.resolve())
    embedding_identity.pop("path", None)
    summary = {
        "schema_version": "1.0",
        "run_id": FINAL_RUN_ID,
        "candidate_experiment_id": EXPERIMENT_ID,
        "benchmark": "ragtruth-test-only",
        "decision_split": "test",
        "decision": "accept_advisory_profile" if all_gates else "reject",
        "protocol": {
            "user_approval": "A/B/C approved 2026-09-04",
            "approval_document_sha256": approval_hash,
            "validation_summary_sha256": VALIDATION_SUMMARY_SHA256,
            "derived_manifest_sha256": arguments.dataset_manifest_sha256.lower(),
            "derived_files": manifest["files"],
            "parent_revision": manifest["parent"]["source_revision"],
            "test_sources": len(source_contexts),
            "test_responses": len(examples),
            "sentence_count": len(records),
            "official_test_accesses": 1,
            "prediction_artifacts_written": 0,
            "model_fits": 0,
            "threshold_calibrations": 0,
            "external_api_calls": 0,
        },
        "features": {
            "baseline": list(FEATURE_NAMES),
            "candidate_addition": list(NLI_FEATURE_NAMES),
            "embedding_model": embedding_identity,
            "nli_model": nli_identity,
            "dense": {**_clean_dense_metadata(dense_metadata), "wall_seconds": dense_seconds},
            "nli": nli_metadata,
        },
        "methods": {
            name: {"thresholds": asdict(thresholds[name]), "test": payload}
            for name, payload in results.items()
        },
        "frozen_models": {
            "baseline": validation["models"]["baseline"],
            "candidate": validation["models"]["candidate"],
        },
        "deltas": deltas,
        "latency": {"incremental_nli_mean_ms_per_response": incremental_latency_ms},
        "gates": {**gates, "all_metric_gates_passed": all_gates},
        "statistics": {"source_clustered_bootstrap": bootstrap},
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
    write_json_atomic(summary_path, summary)
    print(
        json.dumps(
            {
                "baseline": baseline,
                "candidate": candidate,
                "deltas": deltas,
                "gates": summary["gates"],
                "bootstrap": bootstrap,
                "decision": summary["decision"],
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
