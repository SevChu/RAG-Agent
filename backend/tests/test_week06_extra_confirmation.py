from __future__ import annotations

import numpy as np

from scripts.run_week06_extra_confirmation import make_decision


def test_confirmation_requires_all_frozen_gates() -> None:
    strong = make_decision(
        np.asarray([0.1] * 12, dtype=np.float64),
        np.asarray([-0.01] * 12, dtype=np.float64),
    )
    assert strong["gates"]["all_passed"] is True
    assert strong["outcome"] == "minimum_test_eligible"


def test_negative_confidence_lower_bound_blocks_eligibility() -> None:
    uncertain = make_decision(
        np.asarray([0.1, -0.1] * 6, dtype=np.float64),
        np.asarray([-0.01] * 12, dtype=np.float64),
    )
    assert uncertain["gates"]["spearman_bootstrap_ci_lower_positive"] is False
    assert uncertain["gates"]["all_passed"] is False
    assert uncertain["outcome"] == "insufficient_evidence"


def test_rmse_regression_blocks_eligibility() -> None:
    regressing = make_decision(
        np.asarray([0.1] * 12, dtype=np.float64),
        np.asarray([0.01] * 12, dtype=np.float64),
    )
    assert regressing["gates"]["macro_rmse_not_worse"] is False
    assert regressing["outcome"] == "insufficient_evidence"
