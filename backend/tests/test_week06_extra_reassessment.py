from __future__ import annotations

import numpy as np
import pytest

from scripts.run_week06_extra_reassessment import (
    bootstrap_mean_ci,
    exact_sign_flip,
    leave_one_out,
    monte_carlo_sign_flip,
    sign_test,
)


def test_sign_test_counts_ties_and_direction() -> None:
    result = sign_test(np.asarray([1.0, 0.5, 0.0, -0.1], dtype=np.float64))
    assert result["wins"] == 2
    assert result["ties"] == 1
    assert result["losses"] == 1
    assert 0.0 <= result["p_value_two_sided"] <= 1.0


def test_exact_and_monte_carlo_sign_flip_are_bounded() -> None:
    values = np.asarray([0.2, 0.1, -0.05], dtype=np.float64)
    exact = exact_sign_flip(values)
    monte_carlo = monte_carlo_sign_flip(values, seed=42, resamples=2_000)
    assert exact["permutations"] == 8
    assert 0.0 <= exact["p_value"] <= 1.0
    assert 0.0 <= monte_carlo["p_value"] <= 1.0


def test_bootstrap_and_leave_one_out_are_deterministic() -> None:
    values = np.asarray([0.1, 0.2, 0.3], dtype=np.float64)
    assert bootstrap_mean_ci(values, seed=7, resamples=100) == bootstrap_mean_ci(
        values, seed=7, resamples=100
    )
    assert leave_one_out(values) == pytest.approx(
        {"minimum_mean": 0.15, "maximum_mean": 0.25, "positive_count": 3, "total": 3}
    )


def test_invalid_robustness_inputs_are_rejected() -> None:
    empty = np.asarray([], dtype=np.float64)
    with pytest.raises(ValueError, match="non-empty"):
        bootstrap_mean_ci(empty, seed=1)
    with pytest.raises(ValueError, match="1..20"):
        exact_sign_flip(np.ones(21, dtype=np.float64))
    with pytest.raises(ValueError, match="at least two"):
        leave_one_out(np.ones(1, dtype=np.float64))
