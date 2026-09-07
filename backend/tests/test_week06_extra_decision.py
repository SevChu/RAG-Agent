from __future__ import annotations

from scripts.run_week06_extra_decision import day2_decision


def _payload(ci_lower: float, latency_delta: float = 100.0) -> tuple[dict, dict]:
    summary = {
        "status": "complete",
        "identity": {
            "split": "train",
            "query_count": 5500,
            "registered_experiment": {
                "optimization_split": "train",
                "source_split": "train",
                "test_access": "forbidden",
            },
        },
    }
    slices = {
        "comparison": {
            "paired_query_ndcg@10": {
                "query_count": 5500,
                "mean_delta": 0.01,
                "ci95": {"lower": ci_lower, "upper": 0.02},
            },
            "metric_deltas": {"ndcg@10": 0.01},
            "mean_latency_delta_ms": latency_delta,
            "validation_gates": {"recall@100_not_below_dense": True},
        }
    }
    return summary, slices


def test_day2_all_gates_grant_minimum_test_eligibility() -> None:
    summary, slices = _payload(0.001)
    decision = day2_decision(summary, slices)
    assert decision["gates"]["all_passed"] is True
    assert decision["outcome"] == "minimum_test_eligible"
    assert decision["official_test_run"] is False
    assert decision["profile_eligible"] is False


def test_day2_nonpositive_lower_bound_remains_provisional() -> None:
    summary, slices = _payload(0.0)
    decision = day2_decision(summary, slices)
    assert decision["gates"]["paired_bootstrap_ci_lower_positive"] is False
    assert decision["outcome"] == "provisional"


def test_day2_latency_guardrail_is_required() -> None:
    summary, slices = _payload(0.001, latency_delta=800.0)
    decision = day2_decision(summary, slices)
    assert decision["gates"]["latency_regression_within_750ms"] is False
    assert decision["outcome"] == "provisional"
