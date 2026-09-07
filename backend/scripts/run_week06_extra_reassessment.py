from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from scipy.stats import binomtest  # type: ignore[import-untyped]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    BeirAdapter,
    RelevanceJudgment,
    evaluate_retrieval,
    hash_file,
    read_trec_run,
)
from app.evaluation.run_store import write_json_atomic  # noqa: E402

DAY2_SUMMARY_SHA256 = "c49c06e6e9acc7e791d7b01b69789fb1b38fe860d39f8ec3e90831b770e38df0"
DAY2_SLICE_SHA256 = "00003d6949b8fc66f96628004e66f35fc8dcc8cefed72d5295f4b1d0d793805b"
DAY3_SUMMARY_SHA256 = "91e0aeeafcb4f3cbc52a3e39c85cd990564b807162cf6dfec8c8be4d96512b88"
FIQA_DEV_QRELS_SHA256 = "03b27e547cd29dc721c3b93ce8ddd70df6b2d0ce954d8ef3659d386e8cd72c11"
DEFAULT_DAY2_ROOT = (
    _BACKEND_ROOT / "datasets/benchmarks/beir-fiqa-2018/runs/week06-day02/validation"
)
DEFAULT_DAY3_ROOT = _BACKEND_ROOT / "datasets/benchmarks/ragbench/runs/week06-day03/validation"
DEFAULT_OUTPUT = _BACKEND_ROOT / "datasets/benchmarks/week06-extra/reassessment.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reassess Week 6 Day 2/3 with additional train/validation-only evidence"
    )
    parser.add_argument("--day2-root", type=Path, default=DEFAULT_DAY2_ROOT)
    parser.add_argument("--day3-root", type=Path, default=DEFAULT_DAY3_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def bootstrap_mean_ci(
    values: NDArray[np.float64], *, seed: int, resamples: int = 10_000
) -> dict[str, Any]:
    if values.ndim != 1 or not len(values):
        raise ValueError("bootstrap values must be a non-empty vector")
    generator = np.random.default_rng(seed)
    sampled = values[generator.integers(0, len(values), size=(resamples, len(values)))].mean(axis=1)
    return {
        "count": len(values),
        "mean": float(np.mean(values)),
        "ci95": [float(value) for value in np.quantile(sampled, [0.025, 0.975])],
        "positive_fraction": float(np.mean(sampled > 0.0)),
    }


def monte_carlo_sign_flip(
    values: NDArray[np.float64], *, seed: int, resamples: int = 100_000
) -> dict[str, Any]:
    if values.ndim != 1 or not len(values):
        raise ValueError("sign-flip values must be a non-empty vector")
    observed = abs(float(np.mean(values)))
    generator = np.random.default_rng(seed)
    extreme = 0
    completed = 0
    batch_size = 2_000
    while completed < resamples:
        current = min(batch_size, resamples - completed)
        signs = generator.integers(0, 2, size=(current, len(values)), dtype=np.int8) * 2 - 1
        means = np.mean(signs * values, axis=1)
        extreme += int(np.sum(np.abs(means) >= observed - 1e-15))
        completed += current
    return {
        "method": "paired Monte Carlo sign-flip, two-sided",
        "seed": seed,
        "resamples": resamples,
        "p_value": (extreme + 1) / (resamples + 1),
    }


def exact_sign_flip(values: NDArray[np.float64]) -> dict[str, Any]:
    if values.ndim != 1 or not len(values) or len(values) > 20:
        raise ValueError("exact sign-flip requires 1..20 values")
    observed = abs(float(np.mean(values)))
    means = np.asarray(
        [
            np.mean(values * np.asarray(signs, dtype=np.float64))
            for signs in itertools.product((-1.0, 1.0), repeat=len(values))
        ],
        dtype=np.float64,
    )
    return {
        "method": "exact paired sign-flip, two-sided",
        "permutations": len(means),
        "p_value": float(np.mean(np.abs(means) >= observed - 1e-15)),
    }


def sign_test(values: NDArray[np.float64]) -> dict[str, Any]:
    wins = int(np.sum(values > 1e-12))
    losses = int(np.sum(values < -1e-12))
    ties = int(len(values) - wins - losses)
    changed = wins + losses
    p_value = (
        float(binomtest(wins, changed, 0.5, alternative="two-sided").pvalue) if changed else 1.0
    )
    return {"wins": wins, "ties": ties, "losses": losses, "p_value_two_sided": p_value}


def leave_one_out(values: NDArray[np.float64]) -> dict[str, Any]:
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("leave-one-out requires at least two values")
    means = (float(np.sum(values)) - values) / (len(values) - 1)
    return {
        "minimum_mean": float(np.min(means)),
        "maximum_mean": float(np.max(means)),
        "positive_count": int(np.sum(means > 0.0)),
        "total": len(means),
    }


def _load_json(path: Path, expected_hash: str) -> dict[str, Any]:
    if hash_file(path) != expected_hash:
        raise ValueError(f"frozen validation summary hash changed: {path}")
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _group_qrels(
    qrels: tuple[RelevanceJudgment, ...],
) -> dict[str, tuple[RelevanceJudgment, ...]]:
    grouped: defaultdict[str, list[RelevanceJudgment]] = defaultdict(list)
    for judgment in qrels:
        grouped[judgment.query_id].append(judgment)
    return {query_id: tuple(values) for query_id, values in grouped.items()}


def day2_reassessment(root: Path) -> dict[str, Any]:
    summary = _load_json(root / "summary.json", DAY2_SUMMARY_SHA256)
    slice_summary = _load_json(root / "slice-summary.json", DAY2_SLICE_SHA256)
    registered = summary["identity"]["registered_experiment"]
    if (
        registered["experiment_id"] != "w6-d2-dense-direct-rerank"
        or registered["optimization_split"] != "validation"
        or registered["source_split"] != "dev"
        or registered["test_access"] != "forbidden"
    ):
        raise ValueError("Day 2 summary no longer preserves the validation-only boundary")
    runs: dict[str, Any] = {}
    for name in ("rerank", "dense-rerank"):
        path = root / f"{name}.run"
        if hash_file(path) != summary["experiments"][name]["run_sha256"]:
            raise ValueError(f"Day 2 run hash changed: {name}")
        runs[name] = read_trec_run(path)

    raw_root = root.parents[2] / "raw"
    qrels_path = raw_root / "qrels/dev.tsv"
    if hash_file(qrels_path) != FIQA_DEV_QRELS_SHA256:
        raise ValueError("FiQA dev qrels hash changed")
    grouped = _group_qrels(BeirAdapter(raw_root).qrels("dev"))
    query_ids = tuple(sorted(grouped))
    deltas: dict[str, NDArray[np.float64]] = {}
    for metric, cutoff in (("ndcg@10", 10), ("mrr@10", 10), ("map@100", 100)):
        baseline = np.asarray(
            [
                evaluate_retrieval(
                    {query_id: runs["rerank"][query_id]}, grouped[query_id], ks=(cutoff,)
                ).values[metric]
                for query_id in query_ids
            ],
            dtype=np.float64,
        )
        candidate = np.asarray(
            [
                evaluate_retrieval(
                    {query_id: runs["dense-rerank"][query_id]}, grouped[query_id], ks=(cutoff,)
                ).values[metric]
                for query_id in query_ids
            ],
            dtype=np.float64,
        )
        deltas[metric] = candidate - baseline

    ndcg = deltas["ndcg@10"]
    evidence_count = np.asarray([len(grouped[query_id]) for query_id in query_ids], dtype=np.int64)
    original = slice_summary["comparison"]["paired_query_ndcg@10"]
    primary_stable = float(original["ci95"]["lower"]) > 0.0
    return {
        "experiment_id": "w6-d2-dense-direct-rerank",
        "evidence_scope": "existing frozen FiQA dev validation runs; no new labeled split",
        "test_access": "forbidden_and_not_read",
        "summary_sha256": DAY2_SUMMARY_SHA256,
        "slice_summary_sha256": DAY2_SLICE_SHA256,
        "qrels_sha256": FIQA_DEV_QRELS_SHA256,
        "run_sha256": {
            name: summary["experiments"][name]["run_sha256"] for name in ("rerank", "dense-rerank")
        },
        "primary_ndcg@10": {
            "original_paired_bootstrap": original,
            "sign_test_non_ties": sign_test(ndcg),
            "randomization": monte_carlo_sign_flip(ndcg, seed=20260904),
            "leave_one_query_out": leave_one_out(ndcg),
            "single_evidence": bootstrap_mean_ci(ndcg[evidence_count == 1], seed=20260904),
            "multiple_evidence": bootstrap_mean_ci(ndcg[evidence_count > 1], seed=20260904),
        },
        "secondary_delta": {
            metric: bootstrap_mean_ci(values, seed=20260904)
            for metric, values in deltas.items()
            if metric != "ndcg@10"
        },
        "reassessment": "promote" if primary_stable else "provisional",
        "reason": (
            "The registered mean nDCG@10 bootstrap interval still crosses zero. "
            "Robustness analyses are supplementary and do not replace an independent "
            "validation split."
        ),
        "privacy": {"contains_query_ids_or_text": False, "contains_per_query_metrics": False},
    }


def day3_reassessment(root: Path) -> dict[str, Any]:
    summary = _load_json(root / "summary.json", DAY3_SUMMARY_SHA256)
    if summary.get("test_access") != "forbidden_and_not_read":
        raise ValueError("Day 3 summary no longer preserves the validation-only boundary")
    baseline = summary["baseline"]["validation"]["per_subset"]
    candidate = summary["candidate"]["validation"]["per_subset"]
    subsets = tuple(sorted(baseline))
    deltas = np.asarray(
        [
            candidate[subset]["completeness"]["spearman"]
            - baseline[subset]["completeness"]["spearman"]
            for subset in subsets
        ],
        dtype=np.float64,
    )
    counts = np.asarray([baseline[subset]["count"] for subset in subsets], dtype=np.float64)
    order = np.argsort(deltas)
    seed_results = summary["candidate"]["model"]["seed_results"]
    seed_spearman = np.asarray(
        [item["validation"]["spearman"] for item in seed_results], dtype=np.float64
    )
    original = summary["statistics"]["domain_clustered_bootstrap"]
    primary_stable = float(original["ci95"][0]) > 0.0
    return {
        "experiment_id": "w6-d3-two-stage-completeness",
        "evidence_scope": "existing frozen RAGBench train/validation aggregate; no test data",
        "test_access": "forbidden_and_not_read",
        "summary_sha256": DAY3_SUMMARY_SHA256,
        "domain_count": len(deltas),
        "macro_delta": float(np.mean(deltas)),
        "sample_weighted_delta": float(np.average(deltas, weights=counts)),
        "original_domain_bootstrap": original,
        "domain_sign_test": sign_test(deltas),
        "exact_randomization": exact_sign_flip(deltas),
        "leave_one_domain_out": leave_one_out(deltas),
        "sensitivity": {
            "drop_two_largest_positive_macro_delta": float(np.mean(np.delete(deltas, order[-2:]))),
            "drop_two_largest_negative_macro_delta": float(np.mean(np.delete(deltas, order[:2]))),
        },
        "seed_consistency": {
            "count": len(seed_spearman),
            "minimum": float(np.min(seed_spearman)),
            "maximum": float(np.max(seed_spearman)),
            "range": float(np.ptp(seed_spearman)),
        },
        "reassessment": "promote" if primary_stable else "deferred",
        "reason": (
            "The domain bootstrap interval and exact robustness tests do not establish a stable "
            "cross-domain gain; improvements remain concentrated in a few subsets."
        ),
        "privacy": {"contains_sample_ids_or_text": False, "contains_per_sample_metrics": False},
    }


def main() -> int:
    arguments = build_parser().parse_args()
    output = arguments.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to replace completed Extra reassessment: {output}")
    payload = {
        "schema_version": "1.0",
        "run_id": "week06-extra-day2-day3-reassessment",
        "scope": "train/validation-only robustness evidence",
        "day2": day2_reassessment(arguments.day2_root.resolve()),
        "day3": day3_reassessment(arguments.day3_root.resolve()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"summary_sha256={hash_file(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
