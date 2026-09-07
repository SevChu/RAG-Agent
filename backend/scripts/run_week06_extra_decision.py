from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import hash_file  # noqa: E402
from app.evaluation.run_store import write_json_atomic  # noqa: E402

DAY2_SUMMARY_SHA256 = "b3de736e10ba4bf9a6da015fa0f2c9cf3e32d4fa7f3d7e87b8577681d59aa344"
DAY2_SLICE_SHA256 = "03a0f3795e4adf4ba950d2de546ad862abe8125d98ddbe80fe33942cf7403e92"
DAY2_TRAIN_QRELS_SHA256 = "e46a99529aa61b12e086a5c057e4e0ecaeda9502e53d5fe855efce778f1ec59a"
DAY3_OUTER_SHA256 = "9d6422d515b8b52e5375c115795f805776829a7147ff46b729c23ce96c6d4434"
DEFAULT_DAY2_ROOT = (
    _BACKEND_ROOT
    / "datasets/benchmarks/beir-fiqa-2018/runs/week06-extra-day02/train"
)
DEFAULT_DAY3_RESULT = _BACKEND_ROOT / "datasets/benchmarks/week06-extra/outer-domain.json"
DEFAULT_OUTPUT = _BACKEND_ROOT / "datasets/benchmarks/week06-extra/decision.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize the frozen Week 6 Extra decision")
    parser.add_argument("--day2-root", type=Path, default=DEFAULT_DAY2_ROOT)
    parser.add_argument("--day3-result", type=Path, default=DEFAULT_DAY3_RESULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def day2_decision(summary: dict[str, Any], slices: dict[str, Any]) -> dict[str, Any]:
    identity = summary["identity"]
    registered = identity["registered_experiment"]
    if (
        summary.get("status") != "complete"
        or identity.get("split") != "train"
        or identity.get("query_count") != 5500
        or registered.get("optimization_split") != "train"
        or registered.get("source_split") != "train"
        or registered.get("test_access") != "forbidden"
    ):
        raise ValueError("Day 2 output does not preserve the frozen train-only boundary")
    comparison = slices["comparison"]
    paired = comparison["paired_query_ndcg@10"]
    metric_deltas = comparison["metric_deltas"]
    gates = {
        "mean_ndcg_delta_positive": float(paired["mean_delta"]) > 0.0,
        "paired_bootstrap_ci_lower_positive": float(paired["ci95"]["lower"]) > 0.0,
        "recall_at_100_not_below_dense": bool(
            comparison["validation_gates"]["recall@100_not_below_dense"]
        ),
        "latency_regression_within_750ms": (
            float(comparison["mean_latency_delta_ms"]) <= 750.0
        ),
    }
    return {
        "experiment_id": "w6-d2-dense-direct-rerank",
        "evidence": "previously unused FiQA train queries; same finance domain",
        "query_count": paired["query_count"],
        "ndcg_at_10": paired,
        "metric_deltas": metric_deltas,
        "mean_latency_delta_ms": comparison["mean_latency_delta_ms"],
        "gates": {**gates, "all_passed": all(gates.values())},
        "outcome": "minimum_test_eligible" if all(gates.values()) else "provisional",
        "official_test_run": False,
        "profile_eligible": False,
    }


def main() -> int:
    arguments = build_parser().parse_args()
    day2_root = arguments.day2_root.resolve()
    summary_path = day2_root / "summary.json"
    slice_path = day2_root / "slice-summary.json"
    qrels_path = day2_root.parents[2] / "raw/qrels/train.tsv"
    day3_path = arguments.day3_result.resolve()
    expected = {
        summary_path: DAY2_SUMMARY_SHA256,
        slice_path: DAY2_SLICE_SHA256,
        qrels_path: DAY2_TRAIN_QRELS_SHA256,
        day3_path: DAY3_OUTER_SHA256,
    }
    for path, digest in expected.items():
        if hash_file(path) != digest:
            raise ValueError(f"frozen confirmation artifact hash changed: {path}")
    summary = cast(dict[str, Any], json.loads(summary_path.read_text(encoding="utf-8")))
    slices = cast(dict[str, Any], json.loads(slice_path.read_text(encoding="utf-8")))
    day3 = cast(dict[str, Any], json.loads(day3_path.read_text(encoding="utf-8")))
    if day3.get("test_access") != "forbidden_and_not_read":
        raise ValueError("Day 3 result does not preserve the test boundary")
    if day3["decision"]["outcome"] != "insufficient_evidence":
        raise ValueError("Day 3 frozen decision unexpectedly changed")
    payload = {
        "schema_version": "1.0",
        "run_id": "week06-extra-final-decision",
        "target_release": "1.2.1",
        "test_access": "forbidden_and_not_read",
        "day2": day2_decision(summary, slices),
        "day3": {
            "experiment_id": day3["experiment_id"],
            "outcome": "deferred",
            "official_test_run": False,
            "profile_eligible": False,
            "decision": day3["decision"],
        },
        "next_approval": "Day 2 official FiQA test only",
        "privacy": {
            "contains_query_or_sample_ids": False,
            "contains_text": False,
            "contains_per_sample_metrics": False,
        },
        "artifact_sha256": {
            "day2_summary": DAY2_SUMMARY_SHA256,
            "day2_slice_summary": DAY2_SLICE_SHA256,
            "day2_train_qrels": DAY2_TRAIN_QRELS_SHA256,
            "day3_outer_domain": DAY3_OUTER_SHA256,
        },
    }
    output = arguments.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to replace completed Extra decision: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"summary_sha256={hash_file(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
