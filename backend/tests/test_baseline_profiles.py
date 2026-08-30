from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.baseline_profiles import (
    BaselineProfileRegistry,
    BaselineTask,
    load_baseline_profiles,
)

_PROFILES = Path(__file__).resolve().parents[1] / "app" / "evaluation" / "baseline-profiles.json"


def test_frozen_baseline_profiles_match_accepted_week_five_results() -> None:
    registry = load_baseline_profiles(_PROFILES)

    assert registry.release_version == "1.0.0"
    assert registry.test_policy.startswith("test splits are final-report-only")

    retrieval = registry.get("fiqa-dense-retrieval")
    assert retrieval.task == BaselineTask.RETRIEVAL
    assert retrieval.parameters["top_k"] == 100
    assert retrieval.reference_metrics["recall@100"] == pytest.approx(0.7187787349824389)

    hallucination = registry.get("ragtruth-lexical-hallucination")
    assert hallucination.parameters["response_threshold"] == pytest.approx(0.57)
    assert hallucination.reference_metrics["response_auroc"] == pytest.approx(0.7247703625733395)

    trace = registry.get("ragbench-lexical-dense-linear")
    assert trace.parameters["feature_count"] == 28
    assert trace.parameters["adherence_threshold"] == pytest.approx(0.14)
    assert trace.reference_metrics["completeness_spearman"] == pytest.approx(0.3967062587518067)


def test_frozen_baseline_profiles_reject_duplicate_ids() -> None:
    payload = json.loads(_PROFILES.read_text(encoding="utf-8"))
    payload["profiles"].append(dict(payload["profiles"][0]))

    with pytest.raises(ValidationError, match="ids must be unique"):
        BaselineProfileRegistry.model_validate(payload)


def test_frozen_baseline_profiles_require_all_accepted_tasks() -> None:
    payload = json.loads(_PROFILES.read_text(encoding="utf-8"))
    payload["profiles"][-1]["profile_id"] = "replacement-trace-profile"

    with pytest.raises(ValidationError, match="ragbench-lexical-dense-linear"):
        BaselineProfileRegistry.model_validate(payload)


def test_frozen_baseline_profiles_do_not_contain_secrets_or_local_paths() -> None:
    text = _PROFILES.read_text(encoding="utf-8").lower()

    assert "api_key" not in text
    assert "d:\\" not in text
    assert "c:\\" not in text
