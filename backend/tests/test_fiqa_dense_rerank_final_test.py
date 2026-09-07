from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_fiqa_dense_rerank_final_test import (
    final_decision,
    load_parent_decision,
    verify_approval,
)


def test_approval_and_parent_identity_are_frozen() -> None:
    assert len(verify_approval()) == 64
    parent = load_parent_decision(Path("datasets/benchmarks/week06-extra/decision.json"))
    assert parent["day2"]["outcome"] == "minimum_test_eligible"


def test_final_decision_requires_every_gate() -> None:
    paired = {"mean_delta": 0.01, "ci95": {"lower": 0.001, "upper": 0.02}}
    accepted = final_decision(
        paired=paired, recall_delta_from_dense=0.0, latency_delta_ms=749.0
    )
    assert accepted["gates"]["all_passed"] is True
    assert accepted["outcome"] == "accept_advisory_profile"
    rejected = final_decision(
        paired={**paired, "ci95": {"lower": 0.0, "upper": 0.02}},
        recall_delta_from_dense=0.0,
        latency_delta_ms=749.0,
    )
    assert rejected["outcome"] == "reject"


def test_parent_hash_mismatch_is_rejected_before_test_access(tmp_path: Path) -> None:
    changed = tmp_path / "decision.json"
    changed.write_text(json.dumps({"day2": {"outcome": "changed"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="approved frozen identity"):
        load_parent_decision(changed)


def test_final_runner_source_contains_no_training_or_retry_controls() -> None:
    source = Path("scripts/run_fiqa_dense_rerank_final_test.py").read_text(encoding="utf-8")
    assert ".fit(" not in source
    assert "force-methods" not in source
    assert "force=True" not in source
    assert '"model_fits": 0' in source
