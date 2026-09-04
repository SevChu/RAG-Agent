from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from app.evaluation import RagBenchExample
from scripts.run_ragbench_benchmark import CompactDataset, build_compact_dataset
from scripts.run_ragbench_completeness_experiment import (
    evaluate_validation,
    fit_two_stage_completeness,
    metric_deltas,
    validate_registered_experiment,
)


class RecordingAdapter:
    def __init__(self) -> None:
        self.requested_splits: list[str] = []

    def iter_examples(self, *, split: str) -> Iterator[RagBenchExample]:
        self.requested_splits.append(split)
        yield _example(split)


def _example(split: str) -> RagBenchExample:
    return RagBenchExample(
        example_id=f"{split}-row",
        row_index=0,
        subset="covidqa",
        split=split,
        question="What is supported?",
        documents=("The supported answer.",),
        response="The supported answer.",
        generation_model_name="fixture",
        annotating_model_name="fixture",
        adherence_score=True,
        relevance_score=1.0,
        utilization_score=1.0,
        completeness_score=1.0,
        unsupported_response_sentence_keys=(),
        all_relevant_sentence_keys=("0",),
        all_utilized_sentence_keys=("0",),
        published_scores={
            "trulens_groundedness": None,
            "trulens_context_relevance": None,
            "ragas_faithfulness": None,
            "ragas_context_relevance": None,
            "gpt3_adherence": None,
            "gpt3_context_relevance": None,
            "gpt35_utilization": None,
        },
    )


def test_compact_dataset_requests_only_declared_splits() -> None:
    adapter = RecordingAdapter()

    compact = build_compact_dataset(  # type: ignore[arg-type]
        adapter,
        selected_splits=("train", "validation"),
    )

    assert adapter.requested_splits == ["train", "validation"]
    assert compact.splits == ("train", "validation")
    assert "test" not in compact.splits
    assert compact.text_length_chars == (21, 21)
    assert compact.evidence_counts == (1, 1)


def test_registered_day3_experiment_is_train_validation_only() -> None:
    seeds = validate_registered_experiment("w6-d3-two-stage-completeness")

    assert seeds == (42, 43, 44)


def test_two_stage_candidate_changes_only_completeness_scores() -> None:
    generator = np.random.default_rng(7)
    row_count = 60
    features = generator.normal(size=(row_count, 6))
    splits = ("train",) * 45 + ("validation",) * 15
    relevance = np.clip(0.5 + 0.2 * features[:, 0], 0.0, 1.0)
    utilization = np.clip(0.4 + 0.3 * features[:, 1], 0.0, 1.0)
    completeness = np.clip(relevance * utilization + 0.1 * features[:, 2], 0.0, 1.0)
    adherence = (features[:, 3] >= 0).astype(np.int64)
    compact = CompactDataset(
        ids=tuple(f"row-{index}" for index in range(row_count)),
        subsets=("covidqa",) * row_count,
        splits=splits,
        lexical_features=features,
        lexical_scores={},
        adherence=adherence,
        continuous={
            "relevance": relevance,
            "utilization": utilization,
            "completeness": completeness,
        },
        published={},
    )
    masks = {
        split: np.asarray([value == split for value in splits], dtype=np.bool_)
        for split in ("train", "validation")
    }
    baseline = {
        "adherence": adherence.astype(np.float64),
        "relevance": relevance.copy(),
        "utilization": utilization.copy(),
        "completeness": np.clip(0.5 + 0.1 * features[:, 2], 0.0, 1.0),
    }

    candidate, metadata = fit_two_stage_completeness(
        features=features,
        compact=compact,
        masks=masks,
        baseline_scores=baseline,
        baseline_metadata={
            "selected_alphas": {
                "relevance": 1.0,
                "utilization": 1.0,
                "completeness": 1.0,
            }
        },
        seeds=(42,),
    )

    for label in ("adherence", "relevance", "utilization"):
        assert np.array_equal(candidate[label], baseline[label])
    assert candidate["completeness"].shape == (row_count,)
    assert np.all((candidate["completeness"] >= 0.0) & (candidate["completeness"] <= 1.0))
    assert metadata["folds"] == 5


def test_validation_deltas_report_candidate_minus_baseline() -> None:
    row_count = 12
    splits = ("train",) * 6 + ("validation",) * 6
    validation = np.asarray([value == "validation" for value in splits])
    gold = np.linspace(0.0, 1.0, row_count)
    compact = CompactDataset(
        ids=tuple(f"row-{index}" for index in range(row_count)),
        subsets=("covidqa",) * row_count,
        splits=splits,
        lexical_features=np.zeros((row_count, 1)),
        lexical_scores={},
        adherence=np.asarray([index % 2 for index in range(row_count)]),
        continuous={label: gold for label in ("relevance", "utilization", "completeness")},
        published={},
    )
    baseline_scores = {
        "adherence": compact.adherence.astype(np.float64),
        "relevance": gold,
        "utilization": gold,
        "completeness": np.full(row_count, 0.5),
    }
    candidate_scores = {**baseline_scores, "completeness": gold}

    baseline = evaluate_validation(
        compact=compact,
        scores=baseline_scores,
        validation=validation,
    )
    candidate = evaluate_validation(
        compact=compact,
        scores=candidate_scores,
        validation=validation,
    )
    deltas = metric_deltas(baseline, candidate)

    assert deltas["completeness_spearman"] > 0.0
    assert deltas["completeness_rmse"] < 0.0
    assert deltas["relevance_spearman"] == 0.0
    assert deltas["utilization_spearman"] == 0.0
    assert deltas["adherence_auprc"] == 0.0
