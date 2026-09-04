from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.run_ragtruth_nli_experiment import (
    aggregate_nli_pairs,
    metric_deltas,
    stratified_source_split,
    validate_registered_experiment,
)


def test_completed_nli_experiment_cannot_repeat_optimization() -> None:
    with pytest.raises(ValueError, match="experiment is not ready: completed"):
        validate_registered_experiment("w6-d4-sentence-nli-spans")


def test_source_split_is_deterministic_stratified_and_disjoint() -> None:
    source_tasks = {
        **{f"qa-{index}": "QA" for index in range(10)},
        **{f"sum-{index}": "Summary" for index in range(10)},
    }
    first = stratified_source_split(source_tasks, seed=42)
    assert first == stratified_source_split(source_tasks, seed=42)
    assert {name: len(values) for name, values in first.items()} == {
        "fit": 12,
        "calibration": 4,
        "validation": 4,
    }
    assert set().union(*first.values()) == set(source_tasks)
    assert sum(map(len, first.values())) == len(source_tasks)
    for values in first.values():
        assert {source_tasks[source_id] for source_id in values} == {"QA", "Summary"}


def test_nli_pair_aggregation_takes_per_class_maximum() -> None:
    probabilities = np.asarray(
        [[0.1, 0.8, 0.1], [0.7, 0.2, 0.1], [0.2, 0.3, 0.5]], dtype=np.float64
    )
    aggregated = aggregate_nli_pairs(2, [0, 0, 1], probabilities)
    np.testing.assert_allclose(aggregated, [[0.7, 0.8, 0.1], [0.2, 0.3, 0.5]])


def test_metric_deltas_only_compare_registered_outputs() -> None:
    baseline = {
        "span_char": {"f1": 0.2},
        "response": {"auprc": 0.6, "recall": 0.8},
    }
    candidate = {
        "span_char": {"f1": 0.3},
        "response": {"auprc": 0.61, "recall": 0.8},
    }
    deltas = metric_deltas(baseline, candidate)
    assert deltas == pytest.approx(
        {"span_char_f1": 0.1, "response_auprc": 0.01, "response_recall": 0.0}
    )
    assert "sample" not in json.dumps(deltas)
