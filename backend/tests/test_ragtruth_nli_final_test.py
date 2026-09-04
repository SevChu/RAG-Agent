from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.evaluation import hash_file
from scripts.run_ragtruth_nli_final_test import (
    VALIDATION_SUMMARY_SHA256,
    frozen_logistic_scores,
    load_frozen_validation,
    verify_test_dataset,
)


def test_frozen_validation_identity_and_parameters() -> None:
    summary = load_frozen_validation(
        Path("datasets/benchmarks/ragtruth/runs/week06-day04/validation/summary.json")
    )
    assert VALIDATION_SUMMARY_SHA256 == hash_file(
        Path("datasets/benchmarks/ragtruth/runs/week06-day04/validation/summary.json")
    )
    assert summary["models"]["candidate"]["feature_names"][-3:] == [
        "max_contradiction",
        "max_entailment",
        "max_neutral",
    ]


def test_frozen_logistic_scores_are_stable_and_validate_width() -> None:
    features = np.asarray([[0.0, 1.0], [1.0, 0.0]], dtype=np.float64)
    payload = {"coefficients": [1.0, -1.0], "intercept": 0.0}
    np.testing.assert_allclose(
        frozen_logistic_scores(features, payload),
        [1.0 / (1.0 + np.exp(1.0)), 1.0 / (1.0 + np.exp(-1.0))],
    )
    with pytest.raises(ValueError, match="coefficient count"):
        frozen_logistic_scores(features, {"coefficients": [1.0], "intercept": 0.0})


def test_test_dataset_verifier_rejects_manifest_hash_change(tmp_path: Path) -> None:
    root = tmp_path / "test-only"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"dataset_id": "changed"}), encoding="utf-8")
    with pytest.raises(ValueError, match="command-line frozen hash"):
        verify_test_dataset(root, "0" * 64)


def test_final_runner_source_has_no_fit_or_threshold_tuning() -> None:
    source = Path("scripts/run_ragtruth_nli_final_test.py").read_text(encoding="utf-8")
    assert ".fit(" not in source
    assert "tune_thresholds" not in source
    assert "write_predictions" not in source
    assert 'prediction_artifacts_written": 0' in source
