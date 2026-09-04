from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.experiments import (
    ExperimentRegistry,
    ExperimentStatus,
    OptimizationSplit,
    RevisionState,
    SliceClass,
    SliceDimension,
    SliceObservation,
    aggregate_slices,
    load_experiment_registry,
    require_optimization_split,
    slice_memberships,
)

_REGISTRY = Path(__file__).resolve().parents[1] / "app" / "evaluation" / "experiment-registry.json"


def test_week_six_registry_freezes_all_approved_experiments() -> None:
    registry = load_experiment_registry(_REGISTRY)

    assert registry.target_release_version == "1.2.0"
    assert len(registry.experiments) == 3
    assert all(experiment.test_access == "forbidden" for experiment in registry.experiments)
    assert all(
        set(experiment.optimization_splits)
        == {OptimizationSplit.TRAIN, OptimizationSplit.VALIDATION}
        for experiment in registry.experiments
    )

    retrieval = registry.get("w6-d2-dense-direct-rerank")
    assert retrieval.status == ExperimentStatus.READY
    assert retrieval.revisions.all_frozen
    assert retrieval.primary_metric.name == "ndcg@10"
    assert retrieval.guardrail_metrics[0].name == "recall@100"

    completeness = registry.get("w6-d3-two-stage-completeness")
    assert completeness.status == ExperimentStatus.READY
    assert completeness.primary_variable.name == "completeness_architecture"

    nli = registry.get("w6-d4-sentence-nli-spans")
    assert nli.status == ExperimentStatus.COMPLETED
    assert nli.revisions.all_frozen
    assert nli.revisions.datasets[0].name == "ragtruth-train-only"
    assert nli.revisions.models[0].state == RevisionState.FROZEN
    assert nli.revisions.models[0].revision == "6c749ce3425cd33b46d187e45b92bbf96ee12ec7"


def test_registry_rejects_test_split_and_pending_ready_experiment() -> None:
    payload = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    payload["experiments"][0]["optimization_splits"].append("test")

    with pytest.raises(ValidationError, match="optimization_splits"):
        ExperimentRegistry.model_validate(payload)

    payload = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    payload["experiments"][2]["revisions"]["models"][0].update(
        {"revision": None, "sha256": None, "state": "pending_approval"}
    )
    with pytest.raises(ValidationError, match="frozen artifact revisions"):
        ExperimentRegistry.model_validate(payload)


def test_runtime_split_guard_explains_test_approval_boundary() -> None:
    assert require_optimization_split("train") == OptimizationSplit.TRAIN
    assert require_optimization_split("validation") == OptimizationSplit.VALIDATION

    with pytest.raises(ValueError, match="requires later user approval"):
        require_optimization_split("test")


def test_slice_memberships_cover_all_standard_dimensions() -> None:
    observation = SliceObservation(
        split="validation",
        domain="Financial QA",
        class_label=SliceClass.POSITIVE,
        text_length_chars=500,
        evidence_count=2,
        error_types=("Ranking Error", "False Negative"),
        metrics={"ndcg@10": 0.5},
    )

    memberships = slice_memberships(observation)
    assert {item.dimension for item in memberships} == set(SliceDimension)
    assert {item.value for item in memberships} >= {
        "financial-qa",
        "positive",
        "medium",
        "multiple",
        "ranking-error",
        "false-negative",
    }


def test_slice_aggregation_is_numeric_and_contains_no_sample_payload() -> None:
    observations = [
        SliceObservation(
            split="train",
            domain="finance",
            class_label="positive",
            text_length_chars=100,
            evidence_count=1,
            error_types=(),
            metrics={"score": 0.25},
        ),
        SliceObservation(
            split="validation",
            domain="finance",
            class_label="negative",
            text_length_chars=1200,
            evidence_count=0,
            error_types=("false-positive",),
            metrics={"score": 0.75},
        ),
    ]

    aggregates = aggregate_slices(observations)
    finance = next(
        item
        for item in aggregates
        if item.dimension == SliceDimension.DOMAIN
        and item.value == "finance"
        and item.metric == "score"
    )
    assert finance.count == 2
    assert finance.mean == pytest.approx(0.5)
    assert "sample" not in json.dumps(
        [item.model_dump(mode="json") for item in aggregates], sort_keys=True
    )


def test_slice_observation_rejects_test_and_non_finite_metrics() -> None:
    payload = {
        "split": "test",
        "domain": "finance",
        "class_label": "positive",
        "text_length_chars": 10,
        "evidence_count": 1,
        "metrics": {"score": 1.0},
    }
    with pytest.raises(ValidationError, match="split"):
        SliceObservation.model_validate(payload)

    payload["split"] = "validation"
    payload["metrics"] = {"score": float("nan")}
    with pytest.raises(ValidationError, match="finite"):
        SliceObservation.model_validate(payload)
