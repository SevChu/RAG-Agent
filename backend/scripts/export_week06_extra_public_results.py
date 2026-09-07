from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import hash_file  # noqa: E402
from scripts.export_public_benchmark_results import validate_public_payload  # noqa: E402

DECISION_SHA256 = "d3ae9dc0369b91d7278a08ec966a8a9829de66c1324092223ed04041b7b76fb4"
FINAL_TEST_SHA256 = "06ef176923ad83041b0e195d8b53f24a6585c81da6a5abc45d0845500623029b"
OUTER_DOMAIN_SHA256 = "9d6422d515b8b52e5375c115795f805776829a7147ff46b729c23ce96c6d4434"
DEFAULT_DECISION = _BACKEND_ROOT / "datasets/benchmarks/week06-extra/decision.json"
DEFAULT_FINAL_TEST = (
    _BACKEND_ROOT
    / "datasets/benchmarks/beir-fiqa-2018/runs/week06-extra-day02/final-test/summary.json"
)
DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "benchmarks/v1.2.1"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected an object: {path}")
    return payload


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"expected an object for {label}")
    return value


def _verify_inputs(
    decision_path: Path, final_test_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    if hash_file(decision_path) != DECISION_SHA256:
        raise ValueError("Week 6 Extra parent decision hash changed")
    if hash_file(final_test_path) != FINAL_TEST_SHA256:
        raise ValueError("FiQA final-test summary hash changed")

    decision = _load_json(decision_path)
    final_test = _load_json(final_test_path)
    identity = _mapping(final_test["identity"], "final_test.identity")
    gates = _mapping(final_test["gates"], "final_test.gates")
    if (
        decision.get("test_access") != "forbidden_and_not_read"
        or _mapping(decision["day2"], "decision.day2").get("outcome")
        != "minimum_test_eligible"
        or _mapping(decision["day3"], "decision.day3").get("outcome") != "deferred"
    ):
        raise ValueError("parent decision no longer matches the approved pre-test state")
    if (
        final_test.get("status") != "complete"
        or final_test.get("decision") != "reject"
        or final_test.get("decision_split") != "test"
        or identity.get("parent_decision_sha256") != DECISION_SHA256
        or identity.get("official_test_accesses") != 1
        or gates.get("all_passed") is not False
    ):
        raise ValueError("final test does not match the frozen rejection decision")
    return decision, final_test


def build_public_results(
    *, decision: Mapping[str, Any], final_test: Mapping[str, Any]
) -> dict[str, Any]:
    day2 = _mapping(decision["day2"], "decision.day2")
    day3 = _mapping(decision["day3"], "decision.day3")
    final_identity = _mapping(final_test["identity"], "final_test.identity")
    methods = _mapping(final_test["methods"], "final_test.methods")
    baseline = _mapping(methods["rerank"], "methods.rerank")
    candidate = _mapping(methods["dense-rerank"], "methods.dense-rerank")
    comparison = _mapping(final_test["comparison"], "final_test.comparison")

    payload = {
        "schema_version": "1.0",
        "release_version": "1.2.1",
        "generated_on": "2026-09-07",
        "publication_policy": {
            "aggregation_only": True,
            "contains_sample_text": False,
            "contains_row_level_predictions": False,
            "contains_local_paths": False,
            "contains_personal_or_workspace_data": False,
            "raw_datasets_redistributed": False,
            "artifact_hashes_are_identifiers_only": True,
        },
        "profile_registry_changed": False,
        "decisions": {
            "day2_dense_direct_rerank": "reject",
            "day3_two_stage_completeness": "deferred",
            "profiles_added": 0,
        },
        "experiments": {
            "day2_dense_direct_rerank": {
                "confirmation": {
                    "split": "train",
                    "evidence_scope": "previously unused FiQA queries in the same finance domain",
                    "query_count": day2["query_count"],
                    "ndcg_at_10": day2["ndcg_at_10"],
                    "metric_deltas": day2["metric_deltas"],
                    "mean_latency_delta_ms": day2["mean_latency_delta_ms"],
                    "gates": day2["gates"],
                    "outcome": day2["outcome"],
                },
                "official_test": {
                    "accesses": final_identity["official_test_accesses"],
                    "query_count": final_identity["query_count"],
                    "qrels_count": final_identity["qrels_count"],
                    "baseline": {
                        "method": "hybrid-top-100-rerank",
                        "metrics": baseline["metrics"],
                        "mean_latency_ms": _mapping(
                            baseline["latency"], "baseline.latency"
                        )["mean_ms"],
                        "run_sha256": baseline["run_sha256"],
                    },
                    "candidate": {
                        "method": "dense-top-100-rerank",
                        "metrics": candidate["metrics"],
                        "mean_latency_ms": _mapping(
                            candidate["latency"], "candidate.latency"
                        )["mean_ms"],
                        "run_sha256": candidate["run_sha256"],
                    },
                    "comparison": comparison,
                    "gates": final_test["gates"],
                    "decision": final_test["decision"],
                    "model_fits": _mapping(final_test["runtime"], "runtime")["model_fits"],
                    "threshold_calibrations": _mapping(
                        final_test["runtime"], "runtime"
                    )["threshold_calibrations"],
                },
            },
            "day3_two_stage_completeness": {
                "evidence_scope": (
                    "leave-one-domain-out on frozen RAGBench train/validation data"
                ),
                "independence_limit": (
                    "held-out domains were absent from fitting, but the architecture had "
                    "previously been selected after observing these domain families"
                ),
                "official_test_accesses": 0,
                "decision": day3["decision"],
                "outcome": day3["outcome"],
            },
        },
        "artifact_sha256": {
            "pretest_decision": DECISION_SHA256,
            "day2_final_test_summary": FINAL_TEST_SHA256,
            "day2_train_summary": _mapping(
                decision["artifact_sha256"], "artifact_sha256"
            )["day2_summary"],
            "day2_train_slice_summary": _mapping(
                decision["artifact_sha256"], "artifact_sha256"
            )["day2_slice_summary"],
            "day2_train_qrels": _mapping(
                decision["artifact_sha256"], "artifact_sha256"
            )["day2_train_qrels"],
            "day3_outer_domain_summary": OUTER_DOMAIN_SHA256,
            "fiqa_manifest": final_identity["dataset_manifest_sha256"],
            "fiqa_test_qrels": final_identity["test_qrels_sha256"],
        },
        "limitations": [
            (
                "The Day 2 final-test nDCG@10 delta is negative and its paired "
                "bootstrap interval crosses zero."
            ),
            (
                "The Day 2 candidate is rejected and must not enter an advisory "
                "or production profile."
            ),
            (
                "The Day 3 outer-domain confirmation failed all preregistered "
                "gates and remains deferred."
            ),
            (
                "FiQA is English finance-domain retrieval and does not represent "
                "private Chinese traffic."
            ),
            (
                "RAGBench evidence reuses known domain families and is not a new "
                "external dataset."
            ),
            "Published values are offline research evidence, not production answer gates.",
        ],
    }
    validate_public_payload(payload)
    return payload


def _metric_rows(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(experiment: str, split: str, method: str, metric: str, value: Any) -> None:
        if isinstance(value, int | float) and not isinstance(value, bool):
            rows.append(
                {
                    "experiment": experiment,
                    "split": split,
                    "method": method,
                    "metric": metric,
                    "value": repr(value),
                }
            )

    experiments = _mapping(payload["experiments"], "experiments")
    day2 = _mapping(experiments["day2_dense_direct_rerank"], "day2")
    confirmation = _mapping(day2["confirmation"], "day2.confirmation")
    for metric, value in _mapping(
        confirmation["metric_deltas"], "confirmation deltas"
    ).items():
        add(
            "day2_dense_direct_rerank",
            "train",
            "candidate_minus_baseline",
            metric,
            value,
        )
    test = _mapping(day2["official_test"], "day2.official_test")
    for method in ("baseline", "candidate"):
        method_data = _mapping(test[method], method)
        for metric, value in _mapping(
            method_data["metrics"], f"{method}.metrics"
        ).items():
            add("day2_dense_direct_rerank", "test", method, metric, value)
    test_comparison = _mapping(test["comparison"], "test.comparison")
    for metric, value in _mapping(
        test_comparison["metric_deltas"], "test deltas"
    ).items():
        add(
            "day2_dense_direct_rerank",
            "test",
            "candidate_minus_baseline",
            metric,
            value,
        )
    day3 = _mapping(experiments["day3_two_stage_completeness"], "day3")
    day3_decision = _mapping(day3["decision"], "day3.decision")
    add(
        "day3_two_stage_completeness",
        "outer-domain-validation",
        "candidate_minus_baseline",
        "macro_spearman",
        day3_decision["macro_spearman_delta"],
    )
    add(
        "day3_two_stage_completeness",
        "outer-domain-validation",
        "candidate_minus_baseline",
        "macro_rmse",
        day3_decision["macro_rmse_delta"],
    )
    return rows


def export_results(*, decision_path: Path, final_test_path: Path, output_root: Path) -> None:
    decision, final_test = _verify_inputs(decision_path, final_test_path)
    payload = build_public_results(decision=decision, final_test=final_test)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "results.json").write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    with (output_root / "metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("experiment", "split", "method", "metric", "value"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(_metric_rows(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export aggregate-only Week 6 Extra evidence for v1.2.1"
    )
    parser.add_argument("--decision", type=Path, default=DEFAULT_DECISION)
    parser.add_argument("--final-test", type=Path, default=DEFAULT_FINAL_TEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export_results(
        decision_path=args.decision,
        final_test_path=args.final_test,
        output_root=args.output_root,
    )


if __name__ == "__main__":
    main()
