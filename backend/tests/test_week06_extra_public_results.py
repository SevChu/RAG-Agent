from __future__ import annotations

import json
from pathlib import Path

from scripts.export_public_benchmark_results import validate_public_payload

_RESULTS = Path(__file__).resolve().parents[2] / "benchmarks/v1.2.1/results.json"


def test_week06_extra_public_results_are_aggregate_only() -> None:
    payload = json.loads(_RESULTS.read_text(encoding="utf-8"))

    validate_public_payload(payload)
    assert payload["release_version"] == "1.2.1"
    assert payload["profile_registry_changed"] is False
    assert payload["decisions"] == {
        "day2_dense_direct_rerank": "reject",
        "day3_two_stage_completeness": "deferred",
        "profiles_added": 0,
    }


def test_week06_extra_public_results_preserve_final_gates() -> None:
    payload = json.loads(_RESULTS.read_text(encoding="utf-8"))
    experiments = payload["experiments"]
    final_test = experiments["day2_dense_direct_rerank"]["official_test"]
    outer_domain = experiments["day3_two_stage_completeness"]

    assert final_test["accesses"] == 1
    assert final_test["decision"] == "reject"
    assert (
        final_test["comparison"]["metric_deltas"]["ndcg@10"]
        == -0.0005099724782315351
    )
    assert final_test["gates"]["all_passed"] is False
    assert outer_domain["official_test_accesses"] == 0
    assert outer_domain["outcome"] == "deferred"
    assert outer_domain["decision"]["gates"]["all_passed"] is False
