from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import numpy as np
import psutil  # type: ignore[import-untyped]
import sklearn  # type: ignore[import-untyped]
from numpy.typing import NDArray
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]
from sklearn.model_selection import KFold  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    RAGBENCH_SUBSETS,
    ExperimentStatus,
    OptimizationSplit,
    RagBenchAdapter,
    SliceClass,
    SliceObservation,
    aggregate_slices,
    hash_file,
    load_experiment_registry,
    require_optimization_split,
)
from app.evaluation.ragbench_scoring import (  # noqa: E402
    LEXICAL_FEATURE_NAMES,
    clip_predictions,
    continuous_metrics,
)
from app.evaluation.run_store import write_json_atomic  # noqa: E402
from scripts.run_ragbench_benchmark import (  # noqa: E402
    CONTINUOUS_LABELS,
    DEFAULT_EMBEDDING_MODEL,
    DENSE_FEATURE_NAMES,
    EMBEDDING_BATCH_SIZE,
    EXAMPLE_BATCH_SIZE,
    MAX_TEXT_CHARS,
    CompactDataset,
    adherence_metrics,
    build_compact_dataset,
    fit_linear_trace_models,
    hardware_info,
    load_or_compute_dense_features,
    model_identity,
    selected_ragbench_relative_files,
    verify_frozen_dataset,
)

EXPERIMENT_ID = "w6-d3-two-stage-completeness"
OPTIMIZATION_SPLITS = ("train", "validation")
DEFAULT_OUTPUT = (
    _BACKEND_ROOT
    / "datasets"
    / "benchmarks"
    / "ragbench"
    / "runs"
    / "week06-day03"
    / "validation"
)
RIDGE_ALPHAS = (0.1, 1.0, 10.0, 100.0)
INTERMEDIATE_FEATURE_NAMES = (
    "predicted_relevance",
    "predicted_utilization",
    "predicted_minimum",
    "predicted_product",
    "predicted_absolute_gap",
)
BOOTSTRAP_RESAMPLES = 10_000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the registered Week 6 Day 3 RAGBench validation experiment"
    )
    parser.add_argument("--experiment-id", default=EXPERIMENT_ID)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=_BACKEND_ROOT / "datasets" / "benchmarks" / "ragbench",
    )
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--embedding-batch-size", type=int, default=EMBEDDING_BATCH_SIZE)
    parser.add_argument("--example-batch-size", type=int, default=EXAMPLE_BATCH_SIZE)
    parser.add_argument("--max-text-chars", type=int, default=MAX_TEXT_CHARS)
    parser.add_argument("--force-dense", action="store_true")
    return parser


def validate_registered_experiment(experiment_id: str) -> tuple[int, ...]:
    if experiment_id != EXPERIMENT_ID:
        raise ValueError(f"this runner only supports experiment {EXPERIMENT_ID}")
    experiment = load_experiment_registry().get(experiment_id)
    if experiment.status != ExperimentStatus.READY:
        raise ValueError(f"experiment is not ready: {experiment.status.value}")
    if experiment.task.value != "trace_scoring":
        raise ValueError("registered experiment task must be trace_scoring")
    declared = tuple(
        require_optimization_split(split.value).value for split in experiment.optimization_splits
    )
    if declared != OPTIMIZATION_SPLITS:
        raise ValueError("experiment must declare train and validation only, in that order")
    if experiment.test_access != "forbidden":
        raise ValueError("registered experiment must forbid test access")
    return experiment.random_seeds


def fit_two_stage_completeness(
    *,
    features: NDArray[np.float64],
    compact: CompactDataset,
    masks: dict[str, NDArray[np.bool_]],
    baseline_scores: dict[str, NDArray[np.float64]],
    baseline_metadata: dict[str, Any],
    seeds: tuple[int, ...],
) -> tuple[dict[str, NDArray[np.float64]], dict[str, Any]]:
    train_indices = np.flatnonzero(masks["train"])
    validation = masks["validation"]
    if len(train_indices) < 5 or not np.any(validation):
        raise ValueError("two-stage fitting requires train and validation rows")

    selected_alphas = cast(dict[str, float], baseline_metadata["selected_alphas"])
    seed_predictions: list[NDArray[np.float64]] = []
    seed_metadata: list[dict[str, Any]] = []
    for seed in seeds:
        stage_scores = np.empty((features.shape[0], 2), dtype=np.float64)
        folds = KFold(n_splits=5, shuffle=True, random_state=seed)
        for column, label in enumerate(("relevance", "utilization")):
            target = compact.continuous[label]
            alpha = float(selected_alphas[label])
            for fit_positions, holdout_positions in folds.split(train_indices):
                fit_indices = train_indices[fit_positions]
                holdout_indices = train_indices[holdout_positions]
                model = _ridge(alpha)
                model.fit(features[fit_indices], target[fit_indices])
                stage_scores[holdout_indices, column] = model.predict(features[holdout_indices])
            full_model = _ridge(alpha)
            full_model.fit(features[train_indices], target[train_indices])
            stage_scores[validation, column] = full_model.predict(features[validation])

        stage_scores = np.clip(stage_scores, 0.0, 1.0)
        candidate_features = np.column_stack((features, _intermediate_features(stage_scores)))
        target = compact.continuous["completeness"]
        best_key = (float("inf"), float("inf"))
        best_predictions: NDArray[np.float64] | None = None
        best_alpha = 1.0
        for alpha in RIDGE_ALPHAS:
            model = _ridge(alpha)
            model.fit(candidate_features[masks["train"]], target[masks["train"]])
            predictions = np.asarray(model.predict(candidate_features), dtype=np.float64)
            clipped = np.asarray(clip_predictions(predictions.tolist()), dtype=np.float64)
            metrics = continuous_metrics(
                target[validation].tolist(),
                clipped[validation].tolist(),
            )
            key = (metrics.rmse, alpha)
            if key < best_key:
                best_key = key
                best_predictions = clipped
                best_alpha = alpha
        if best_predictions is None:
            raise RuntimeError("failed to fit two-stage completeness model")
        seed_predictions.append(best_predictions)
        seed_metrics = continuous_metrics(
            target[validation].tolist(),
            best_predictions[validation].tolist(),
        )
        seed_metadata.append(
            {
                "seed": seed,
                "selected_alpha": best_alpha,
                "validation": asdict(seed_metrics),
            }
        )

    completeness = np.mean(np.vstack(seed_predictions), axis=0)
    candidate_scores = {label: values.copy() for label, values in baseline_scores.items()}
    candidate_scores["completeness"] = completeness
    return candidate_scores, {
        "algorithm": "cross-fitted relevance/utilization representation + Ridge",
        "folds": 5,
        "seeds": list(seeds),
        "ridge_alpha_grid": list(RIDGE_ALPHAS),
        "raw_feature_count": int(features.shape[1]),
        "intermediate_feature_names": list(INTERMEDIATE_FEATURE_NAMES),
        "candidate_feature_count": int(features.shape[1] + len(INTERMEDIATE_FEATURE_NAMES)),
        "seed_results": seed_metadata,
        "ensemble": "arithmetic mean across registered seeds",
    }


def evaluate_validation(
    *,
    compact: CompactDataset,
    scores: dict[str, NDArray[np.float64]],
    validation: NDArray[np.bool_],
) -> dict[str, Any]:
    adherence = adherence_metrics(
        compact.adherence[validation],
        scores["adherence"][validation],
        threshold=0.5,
    )
    result: dict[str, Any] = {
        "overall": {
            "adherence": adherence,
            **{
                label: asdict(
                    continuous_metrics(
                        compact.continuous[label][validation].tolist(),
                        scores[label][validation].tolist(),
                    )
                )
                for label in CONTINUOUS_LABELS
            },
        },
        "per_subset": {},
    }
    subset_values = np.asarray(compact.subsets)
    for subset in RAGBENCH_SUBSETS:
        subset_mask = np.logical_and(validation, subset_values == subset)
        if not np.any(subset_mask):
            continue
        result["per_subset"][subset] = {
            "count": int(np.sum(subset_mask)),
            **{
                label: asdict(
                    continuous_metrics(
                        compact.continuous[label][subset_mask].tolist(),
                        scores[label][subset_mask].tolist(),
                    )
                )
                for label in CONTINUOUS_LABELS
            },
        }
    return result


def metric_deltas(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float]:
    baseline_overall = baseline["overall"]
    candidate_overall = candidate["overall"]
    return {
        "completeness_spearman": (
            candidate_overall["completeness"]["spearman"]
            - baseline_overall["completeness"]["spearman"]
        ),
        "completeness_rmse": (
            candidate_overall["completeness"]["rmse"]
            - baseline_overall["completeness"]["rmse"]
        ),
        "relevance_spearman": (
            candidate_overall["relevance"]["spearman"]
            - baseline_overall["relevance"]["spearman"]
        ),
        "utilization_spearman": (
            candidate_overall["utilization"]["spearman"]
            - baseline_overall["utilization"]["spearman"]
        ),
        "adherence_auprc": (
            candidate_overall["adherence"]["auprc"]
            - baseline_overall["adherence"]["auprc"]
        ),
    }


def domain_bootstrap(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    seed: int,
) -> dict[str, Any]:
    deltas = np.asarray(
        [
            candidate["per_subset"][subset]["completeness"]["spearman"]
            - baseline["per_subset"][subset]["completeness"]["spearman"]
            for subset in RAGBENCH_SUBSETS
        ],
        dtype=np.float64,
    )
    generator = np.random.default_rng(seed)
    resampled = np.mean(
        deltas[generator.integers(0, len(deltas), size=(BOOTSTRAP_RESAMPLES, len(deltas)))],
        axis=1,
    )
    return {
        "unit": "RAGBench subset",
        "metric": "macro completeness Spearman delta",
        "seed": seed,
        "resamples": BOOTSTRAP_RESAMPLES,
        "observed_mean": float(np.mean(deltas)),
        "ci95": [float(value) for value in np.quantile(resampled, [0.025, 0.975])],
        "positive_fraction": float(np.mean(resampled > 0.0)),
        "wins": int(np.sum(deltas > 0.0)),
        "ties": int(np.sum(deltas == 0.0)),
        "losses": int(np.sum(deltas < 0.0)),
    }


def build_slice_summary(
    *,
    compact: CompactDataset,
    validation: NDArray[np.bool_],
    baseline_scores: dict[str, NDArray[np.float64]],
    candidate_scores: dict[str, NDArray[np.float64]],
) -> dict[str, Any]:
    if len(compact.text_length_chars) != len(compact.ids):
        raise ValueError("RAGBench text-length metadata is incomplete")
    if len(compact.evidence_counts) != len(compact.ids):
        raise ValueError("RAGBench evidence-count metadata is incomplete")
    observations: list[SliceObservation] = []
    gold = compact.continuous["completeness"]
    for position in np.flatnonzero(validation):
        index = int(position)
        baseline_error = abs(float(baseline_scores["completeness"][index] - gold[index]))
        candidate_error = abs(float(candidate_scores["completeness"][index] - gold[index]))
        difference = baseline_error - candidate_error
        error_type = "tie"
        if difference > 1e-12:
            error_type = "candidate-better"
        elif difference < -1e-12:
            error_type = "candidate-worse"
        observations.append(
            SliceObservation(
                split=OptimizationSplit.VALIDATION,
                domain=compact.subsets[index],
                class_label=(
                    SliceClass.POSITIVE if gold[index] >= 0.5 else SliceClass.NEGATIVE
                ),
                text_length_chars=compact.text_length_chars[index],
                evidence_count=compact.evidence_counts[index],
                error_types=(error_type,),
                metrics={
                    "baseline_abs_error": baseline_error,
                    "candidate_abs_error": candidate_error,
                    "abs_error_improvement": difference,
                },
            )
        )
    return {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "split": "validation",
        "contains_sample_ids_or_text": False,
        "dimensions": [
            "domain",
            "class",
            "length",
            "evidence_count",
            "error_type",
        ],
        "aggregates": [item.model_dump(mode="json") for item in aggregate_slices(observations)],
    }


def _ridge(alpha: float) -> Any:
    return make_pipeline(StandardScaler(), Ridge(alpha=alpha))


def _intermediate_features(stage_scores: NDArray[np.float64]) -> NDArray[np.float64]:
    relevance = stage_scores[:, 0]
    utilization = stage_scores[:, 1]
    return np.column_stack(
        (
            relevance,
            utilization,
            np.minimum(relevance, utilization),
            relevance * utilization,
            np.abs(relevance - utilization),
        )
    )


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.embedding_batch_size < 1 or arguments.example_batch_size < 1:
        raise ValueError("batch sizes must be positive")
    if arguments.max_text_chars < 256:
        raise ValueError("max text chars must be at least 256")
    seeds = validate_registered_experiment(arguments.experiment_id)

    started = time.perf_counter()
    process = psutil.Process()
    dataset_root = arguments.dataset_root.resolve()
    manifest = verify_frozen_dataset(dataset_root, splits=OPTIMIZATION_SPLITS)
    adapter = RagBenchAdapter(dataset_root / "raw")
    compact = build_compact_dataset(adapter, selected_splits=OPTIMIZATION_SPLITS)
    if "test" in compact.splits:
        raise ValueError("test split reached the optimization dataset")
    masks = {
        split: np.asarray([value == split for value in compact.splits], dtype=np.bool_)
        for split in OPTIMIZATION_SPLITS
    }
    if any(not np.any(mask) for mask in masks.values()):
        raise ValueError("RAGBench train and validation splits are required")

    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    dense_started = time.perf_counter()
    dense_features, dense_metadata = load_or_compute_dense_features(
        adapter=adapter,
        row_count=len(compact.ids),
        model_path=arguments.embedding_model.resolve(),
        output=output,
        device_preference=arguments.device,
        embedding_batch_size=arguments.embedding_batch_size,
        example_batch_size=arguments.example_batch_size,
        max_text_chars=arguments.max_text_chars,
        manifest=manifest,
        force=arguments.force_dense,
        splits=OPTIMIZATION_SPLITS,
    )
    dense_seconds = time.perf_counter() - dense_started
    features = np.column_stack((compact.lexical_features, dense_features))
    baseline_scores, baseline_model = fit_linear_trace_models(
        features=features,
        compact=compact,
        masks=masks,
    )
    candidate_scores, candidate_model = fit_two_stage_completeness(
        features=features,
        compact=compact,
        masks=masks,
        baseline_scores=baseline_scores,
        baseline_metadata=baseline_model,
        seeds=seeds,
    )
    validation = masks["validation"]
    baseline = evaluate_validation(
        compact=compact,
        scores=baseline_scores,
        validation=validation,
    )
    candidate = evaluate_validation(
        compact=compact,
        scores=candidate_scores,
        validation=validation,
    )
    deltas = metric_deltas(baseline, candidate)
    gates = {
        "completeness_spearman": deltas["completeness_spearman"] >= 0.0,
        "completeness_rmse": deltas["completeness_rmse"] <= 0.0,
        "relevance_spearman": deltas["relevance_spearman"] >= -0.01,
        "utilization_spearman": deltas["utilization_spearman"] >= -0.01,
        "adherence_auprc": deltas["adherence_auprc"] >= -0.01,
    }

    slice_path = output / "slice-summary.json"
    write_json_atomic(
        slice_path,
        build_slice_summary(
            compact=compact,
            validation=validation,
            baseline_scores=baseline_scores,
            candidate_scores=candidate_scores,
        ),
    )
    model = model_identity(arguments.embedding_model.resolve())
    model.pop("path", None)
    relative_files = selected_ragbench_relative_files(OPTIMIZATION_SPLITS)
    summary = {
        "schema_version": "1.0",
        "experiment_id": arguments.experiment_id,
        "benchmark": "ragbench",
        "decision_split": "validation",
        "test_access": "forbidden_and_not_read",
        "protocol": {
            "dataset_revision": manifest.source_revision,
            "verified_files": {path: manifest.files[path] for path in relative_files},
            "evaluated_splits": {
                split: int(np.sum(mask)) for split, mask in masks.items()
            },
            "excluded_unlabeled_rows": compact.excluded_unlabeled_rows,
            "seed": list(seeds),
            "external_judge_calls": 0,
            "prediction_artifacts_written": 0,
        },
        "features": {
            "lexical": list(LEXICAL_FEATURE_NAMES),
            "dense": list(DENSE_FEATURE_NAMES),
            "dense_metadata": dense_metadata,
            "embedding_model": model,
        },
        "baseline": {
            "name": "single-stage-linear",
            "model": baseline_model,
            "validation": baseline,
        },
        "candidate": {
            "name": "two-stage-relevance-utilization-completeness",
            "model": candidate_model,
            "validation": candidate,
        },
        "deltas": deltas,
        "gates": {**gates, "all_passed": all(gates.values())},
        "statistics": {
            "domain_clustered_bootstrap": domain_bootstrap(
                baseline,
                candidate,
                seed=seeds[0],
            )
        },
        "runtime": {
            "wall_seconds": time.perf_counter() - started,
            "dense_wall_seconds": dense_seconds,
            "peak_working_set_bytes": process.memory_info().peak_wset,
            "hardware": hardware_info(),
            "numpy_version": np.__version__,
            "scikit_learn_version": sklearn.__version__,
            "external_api_calls": 0,
            "external_tokens": 0,
            "new_model_downloads": 0,
        },
        "artifacts": {
            "slice_summary": slice_path.name,
            "slice_summary_sha256": hash_file(slice_path),
            "implementation_sha256": {
                "experiment_runner": hash_file(Path(__file__)),
                "ragbench_runner": hash_file(
                    _BACKEND_ROOT / "scripts" / "run_ragbench_benchmark.py"
                ),
            },
        },
    }
    summary_path = output / "summary.json"
    write_json_atomic(summary_path, summary)
    print(
        json.dumps(
            {
                "experiment_id": arguments.experiment_id,
                "evaluated_splits": summary["protocol"]["evaluated_splits"],
                "baseline": baseline["overall"],
                "candidate": candidate["overall"],
                "deltas": deltas,
                "gates": summary["gates"],
                "bootstrap": summary["statistics"]["domain_clustered_bootstrap"],
                "summary": str(summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
