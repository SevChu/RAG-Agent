from __future__ import annotations

import pytest

from app.evaluation.ragbench_scoring import (
    LEXICAL_FEATURE_NAMES,
    clip_predictions,
    continuous_metrics,
    lexical_trace_scores,
    ragbench_lexical_features,
    tune_binary_threshold,
)


def test_lexical_scores_reward_supported_relevant_text() -> None:
    supported = ragbench_lexical_features(
        question="Where is the Eiffel Tower?",
        documents=("The Eiffel Tower is in Paris.",),
        response="The Eiffel Tower is in Paris.",
    )
    unsupported = ragbench_lexical_features(
        question="Where is the Eiffel Tower?",
        documents=("The Eiffel Tower is in Paris.",),
        response="The Eiffel Tower is in London.",
    )

    assert len(supported) == len(LEXICAL_FEATURE_NAMES)
    assert (
        lexical_trace_scores(supported)["adherence"]
        > lexical_trace_scores(unsupported)["adherence"]
    )


def test_trace_scores_remain_in_unit_interval() -> None:
    features = ragbench_lexical_features(
        question="What number is reported?",
        documents=("The report states 42 units.", "Background only."),
        response="It reports 42 units.",
    )

    assert all(0.0 <= score <= 1.0 for score in lexical_trace_scores(features).values())


def test_threshold_tuning_uses_f1_then_precision() -> None:
    threshold = tune_binary_threshold(
        [0, 0, 1, 1],
        [0.1, 0.4, 0.6, 0.9],
        step=0.1,
    )

    assert threshold == pytest.approx(0.6)


def test_continuous_metrics_include_tie_aware_spearman() -> None:
    metrics = continuous_metrics(
        [0.0, 0.5, 0.5, 1.0],
        [0.0, 0.4, 0.4, 0.9],
    )

    assert metrics.count == 4
    assert metrics.mae == pytest.approx(0.075)
    assert metrics.rmse == pytest.approx((0.03 / 4) ** 0.5)
    assert metrics.pearson > 0.99
    assert metrics.spearman == pytest.approx(1.0)


def test_continuous_metrics_reject_empty_or_mismatched_inputs() -> None:
    with pytest.raises(ValueError, match="same non-zero length"):
        continuous_metrics([], [])
    with pytest.raises(ValueError, match="same non-zero length"):
        continuous_metrics([0.0], [0.0, 1.0])
    assert clip_predictions([-1.0, 0.5, 2.0]) == [0.0, 0.5, 1.0]
