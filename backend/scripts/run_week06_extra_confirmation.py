from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]
from sklearn.model_selection import KFold  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import RAGBENCH_SUBSETS, RagBenchAdapter, hash_file  # noqa: E402
from app.evaluation.ragbench_scoring import clip_predictions, continuous_metrics  # noqa: E402
from app.evaluation.run_store import write_json_atomic  # noqa: E402
from scripts.run_ragbench_benchmark import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL,
    CompactDataset,
    build_compact_dataset,
    load_or_compute_dense_features,
    verify_frozen_dataset,
)
from scripts.run_ragbench_completeness_experiment import (  # noqa: E402
    INTERMEDIATE_FEATURE_NAMES,
    _intermediate_features,
)
from scripts.run_week06_extra_reassessment import (  # noqa: E402
    bootstrap_mean_ci,
    exact_sign_flip,
    leave_one_out,
    sign_test,
)

EXPERIMENT_ID = "w6-extra-d3-ragbench-outer-domain"
PARENT_SUMMARY_SHA256 = "91e0aeeafcb4f3cbc52a3e39c85cd990564b807162cf6dfec8c8be4d96512b88"
DENSE_CACHE_SHA256 = "0230b67dfed86e45851a23740698b42a3b70332d87bab524f4f3ad0227a1a35e"
FROZEN_ALPHA = 100.0
FROZEN_SEEDS = (42, 43, 44)
FROZEN_FOLDS = 5
BOOTSTRAP_SEED = 20260906
DEFAULT_DATASET_ROOT = _BACKEND_ROOT / "datasets/benchmarks/ragbench"
DEFAULT_PARENT_ROOT = DEFAULT_DATASET_ROOT / "runs/week06-day03/validation"
DEFAULT_OUTPUT = _BACKEND_ROOT / "datasets/benchmarks/week06-extra/outer-domain.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the preregistered Week 6 Extra RAGBench outer-domain confirmation"
    )
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--parent-root", type=Path, default=DEFAULT_PARENT_ROOT)
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def _ridge() -> Any:
    return make_pipeline(StandardScaler(), Ridge(alpha=FROZEN_ALPHA))


def _predict_candidate(
    *,
    features: NDArray[np.float64],
    compact: CompactDataset,
    train_indices: NDArray[np.int64],
    evaluation_indices: NDArray[np.int64],
) -> NDArray[np.float64]:
    seed_predictions: list[NDArray[np.float64]] = []
    for seed in FROZEN_SEEDS:
        train_stage = np.empty((len(train_indices), 2), dtype=np.float64)
        evaluation_stage = np.empty((len(evaluation_indices), 2), dtype=np.float64)
        folds = KFold(n_splits=FROZEN_FOLDS, shuffle=True, random_state=seed)
        for column, label in enumerate(("relevance", "utilization")):
            target = compact.continuous[label]
            for fit_positions, holdout_positions in folds.split(train_indices):
                model = _ridge()
                model.fit(
                    features[train_indices[fit_positions]],
                    target[train_indices[fit_positions]],
                )
                train_stage[holdout_positions, column] = model.predict(
                    features[train_indices[holdout_positions]]
                )
            full_model = _ridge()
            full_model.fit(features[train_indices], target[train_indices])
            evaluation_stage[:, column] = full_model.predict(features[evaluation_indices])

        train_stage = np.clip(train_stage, 0.0, 1.0)
        evaluation_stage = np.clip(evaluation_stage, 0.0, 1.0)
        train_features = np.column_stack(
            (features[train_indices], _intermediate_features(train_stage))
        )
        evaluation_features = np.column_stack(
            (features[evaluation_indices], _intermediate_features(evaluation_stage))
        )
        model = _ridge()
        model.fit(train_features, compact.continuous["completeness"][train_indices])
        seed_predictions.append(np.asarray(model.predict(evaluation_features), dtype=np.float64))
    averaged = np.mean(np.vstack(seed_predictions), axis=0)
    return np.asarray(clip_predictions(averaged.tolist()), dtype=np.float64)


def evaluate_outer_domains(
    *, features: NDArray[np.float64], compact: CompactDataset
) -> tuple[list[dict[str, Any]], NDArray[np.float64], NDArray[np.float64]]:
    subsets = np.asarray(compact.subsets)
    splits = np.asarray(compact.splits)
    gold = compact.continuous["completeness"]
    results: list[dict[str, Any]] = []
    spearman_deltas: list[float] = []
    rmse_deltas: list[float] = []
    for domain in RAGBENCH_SUBSETS:
        train_indices = np.flatnonzero(np.logical_and(splits == "train", subsets != domain))
        evaluation_indices = np.flatnonzero(
            np.logical_and(splits == "validation", subsets == domain)
        )
        if len(train_indices) < FROZEN_FOLDS or not len(evaluation_indices):
            raise ValueError(f"insufficient outer-domain rows for {domain}")
        if np.any(subsets[train_indices] == domain):
            raise ValueError(f"held-out domain leaked into training: {domain}")
        if set(np.asarray(compact.ids)[train_indices]).intersection(
            np.asarray(compact.ids)[evaluation_indices]
        ):
            raise ValueError(f"sample identity overlap detected for {domain}")

        baseline_model = _ridge()
        baseline_model.fit(features[train_indices], gold[train_indices])
        baseline_predictions = np.asarray(
            clip_predictions(baseline_model.predict(features[evaluation_indices]).tolist()),
            dtype=np.float64,
        )
        candidate_predictions = _predict_candidate(
            features=features,
            compact=compact,
            train_indices=train_indices,
            evaluation_indices=evaluation_indices,
        )
        baseline = asdict(
            continuous_metrics(gold[evaluation_indices].tolist(), baseline_predictions.tolist())
        )
        candidate = asdict(
            continuous_metrics(gold[evaluation_indices].tolist(), candidate_predictions.tolist())
        )
        spearman_delta = float(candidate["spearman"] - baseline["spearman"])
        rmse_delta = float(candidate["rmse"] - baseline["rmse"])
        spearman_deltas.append(spearman_delta)
        rmse_deltas.append(rmse_delta)
        results.append(
            {
                "domain": domain,
                "train_rows_other_domains": len(train_indices),
                "validation_rows_held_out_domain": len(evaluation_indices),
                "baseline": baseline,
                "candidate": candidate,
                "delta": {"completeness_spearman": spearman_delta, "completeness_rmse": rmse_delta},
            }
        )
    return (
        results,
        np.asarray(spearman_deltas, dtype=np.float64),
        np.asarray(rmse_deltas, dtype=np.float64),
    )


def make_decision(
    spearman_deltas: NDArray[np.float64], rmse_deltas: NDArray[np.float64]
) -> dict[str, Any]:
    bootstrap = bootstrap_mean_ci(spearman_deltas, seed=BOOTSTRAP_SEED)
    randomization = exact_sign_flip(spearman_deltas)
    gates = {
        "macro_spearman_delta_positive": float(np.mean(spearman_deltas)) > 0.0,
        "spearman_bootstrap_ci_lower_positive": float(bootstrap["ci95"][0]) > 0.0,
        "exact_sign_flip_p_below_0_05": float(randomization["p_value"]) < 0.05,
        "macro_rmse_not_worse": float(np.mean(rmse_deltas)) <= 0.0,
    }
    return {
        "macro_spearman_delta": float(np.mean(spearman_deltas)),
        "macro_rmse_delta": float(np.mean(rmse_deltas)),
        "spearman_bootstrap": bootstrap,
        "exact_randomization": randomization,
        "domain_sign_test": sign_test(spearman_deltas),
        "leave_one_domain_out": leave_one_out(spearman_deltas),
        "gates": {**gates, "all_passed": all(gates.values())},
        "outcome": "minimum_test_eligible" if all(gates.values()) else "insufficient_evidence",
    }


def main() -> int:
    arguments = build_parser().parse_args()
    started = time.perf_counter()
    dataset_root = arguments.dataset_root.resolve()
    parent_root = arguments.parent_root.resolve()
    output = arguments.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to replace completed confirmation: {output}")
    parent_summary_path = parent_root / "summary.json"
    if hash_file(parent_summary_path) != PARENT_SUMMARY_SHA256:
        raise ValueError("approved Day 3 parent summary hash changed")
    parent = cast(dict[str, Any], json.loads(parent_summary_path.read_text(encoding="utf-8")))
    if parent.get("test_access") != "forbidden_and_not_read":
        raise ValueError("parent experiment did not preserve the test boundary")
    if parent["baseline"]["model"]["selected_alphas"] != {
        "relevance": FROZEN_ALPHA,
        "utilization": FROZEN_ALPHA,
        "completeness": FROZEN_ALPHA,
    }:
        raise ValueError("parent baseline alphas differ from the frozen protocol")
    seed_results = parent["candidate"]["model"]["seed_results"]
    if tuple(item["seed"] for item in seed_results) != FROZEN_SEEDS or any(
        item["selected_alpha"] != FROZEN_ALPHA for item in seed_results
    ):
        raise ValueError("parent candidate seeds/alphas differ from the frozen protocol")

    manifest = verify_frozen_dataset(dataset_root, splits=("train", "validation"))
    adapter = RagBenchAdapter(dataset_root / "raw")
    compact = build_compact_dataset(adapter, selected_splits=("train", "validation"))
    if "test" in compact.splits:
        raise ValueError("test split reached the confirmation dataset")
    dense_features, dense_metadata = load_or_compute_dense_features(
        adapter=adapter,
        row_count=len(compact.ids),
        model_path=arguments.embedding_model.resolve(),
        output=parent_root,
        device_preference="auto",
        embedding_batch_size=16,
        example_batch_size=64,
        max_text_chars=8000,
        manifest=manifest,
        force=False,
        splits=("train", "validation"),
    )
    if (
        dense_metadata.get("cache") != "hit"
        or dense_metadata.get("cache_sha256") != DENSE_CACHE_SHA256
    ):
        raise ValueError("frozen dense feature cache was not reused exactly")
    features = np.column_stack((compact.lexical_features, dense_features))
    domains, spearman_deltas, rmse_deltas = evaluate_outer_domains(
        features=features, compact=compact
    )
    payload = {
        "schema_version": "1.0",
        "experiment_id": EXPERIMENT_ID,
        "target_release": "1.2.1",
        "evidence_tier": "outer-domain confirmation on existing frozen train/validation data",
        "independence_limit": (
            "Each evaluation domain is absent from its fitted model, but the candidate "
            "architecture "
            "was selected after the parent experiment observed these 12 domains."
        ),
        "test_access": "forbidden_and_not_read",
        "protocol": {
            "parent_summary_sha256": PARENT_SUMMARY_SHA256,
            "dense_cache_sha256": DENSE_CACHE_SHA256,
            "dataset_revision": manifest.source_revision,
            "held_out_unit": "RAGBench subset/domain",
            "fit_split": "train rows from the other 11 domains",
            "evaluation_split": "validation rows from the held-out domain",
            "ridge_alpha": FROZEN_ALPHA,
            "folds": FROZEN_FOLDS,
            "seeds": list(FROZEN_SEEDS),
            "bootstrap_seed": BOOTSTRAP_SEED,
            "feature_count": int(features.shape[1]),
            "intermediate_feature_names": list(INTERMEDIATE_FEATURE_NAMES),
        },
        "domains": domains,
        "decision": make_decision(spearman_deltas, rmse_deltas),
        "privacy": {"contains_sample_ids_or_text": False, "contains_per_sample_metrics": False},
        "runtime": {"wall_seconds": time.perf_counter() - started, "new_downloads": 0},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"summary_sha256={hash_file(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
