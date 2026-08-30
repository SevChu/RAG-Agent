from __future__ import annotations

import numpy as np

from scripts.run_ragbench_benchmark import (
    PUBLISHED_TARGETS,
    CompactDataset,
    evaluate_method,
    evaluate_published_scorers,
    fit_linear_trace_models,
)


def test_linear_trace_models_fit_only_declared_splits_and_score_all_rows() -> None:
    row_count = 18
    splits = ("train",) * 8 + ("validation",) * 4 + ("test",) * 6
    features = np.asarray(
        [[index / row_count, (index % 3) / 2] for index in range(row_count)],
        dtype=np.float64,
    )
    adherence = np.asarray(
        [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        dtype=np.int64,
    )
    continuous = {
        "relevance": np.linspace(0.0, 1.0, row_count),
        "utilization": np.linspace(1.0, 0.0, row_count),
        "completeness": np.asarray([(index % 4) / 3 for index in range(row_count)]),
    }
    compact = CompactDataset(
        ids=tuple(f"row-{index}" for index in range(row_count)),
        subsets=("covidqa",) * row_count,
        splits=splits,
        lexical_features=features,
        lexical_scores={
            "adherence": features[:, 0],
            **continuous,
        },
        adherence=adherence,
        continuous=continuous,
        published={},
    )
    masks = {
        split: np.asarray([value == split for value in splits], dtype=np.bool_)
        for split in ("train", "validation", "test")
    }

    scores, metadata = fit_linear_trace_models(
        features=features,
        compact=compact,
        masks=masks,
    )

    assert set(scores) == {
        "adherence",
        "relevance",
        "utilization",
        "completeness",
    }
    assert all(values.shape == (row_count,) for values in scores.values())
    assert all(np.all(np.logical_and(values >= 0.0, values <= 1.0)) for values in scores.values())
    assert metadata["selected_alphas"].keys() == continuous.keys()


def test_evaluate_method_reports_each_official_subset() -> None:
    subsets = (
        "covidqa",
        "cuad",
        "delucionqa",
        "emanual",
        "expertqa",
        "finqa",
        "hagrid",
        "hotpotqa",
        "msmarco",
        "pubmedqa",
        "tatqa",
        "techqa",
    )
    splits = ("validation",) * len(subsets) + ("test",) * len(subsets)
    row_count = len(splits)
    adherence = np.asarray([index % 2 for index in range(row_count)], dtype=np.int64)
    continuous = {
        label: np.linspace(0.0, 1.0, row_count)
        for label in ("relevance", "utilization", "completeness")
    }
    compact = CompactDataset(
        ids=tuple(f"row-{index}" for index in range(row_count)),
        subsets=subsets + subsets,
        splits=splits,
        lexical_features=np.zeros((row_count, 1), dtype=np.float64),
        lexical_scores={},
        adherence=adherence,
        continuous=continuous,
        published={},
    )
    masks = {
        "train": np.zeros(row_count, dtype=np.bool_),
        "validation": np.asarray(
            [value == "validation" for value in splits],
            dtype=np.bool_,
        ),
        "test": np.asarray([value == "test" for value in splits], dtype=np.bool_),
    }
    scores = {
        "adherence": adherence.astype(np.float64),
        **continuous,
    }

    result = evaluate_method(compact=compact, scores=scores, masks=masks)

    assert result["adherence"]["f1"] == 1.0
    assert set(result["per_subset"]) == set(subsets)
    assert all(payload["count"] == 1 for payload in result["per_subset"].values())


def test_published_scorers_use_fixed_threshold_without_validation_and_reject_overflow() -> None:
    splits = ("validation", "validation", "test", "test", "test", "test")
    row_count = len(splits)
    values = np.asarray([np.nan, np.nan, 0.2, -1.0, 0.8, 1.0], dtype=np.float64)
    adherence = np.asarray([0, 1, 0, 0, 1, 1], dtype=np.int64)
    continuous = {
        label: np.asarray([0.0, 1.0, 0.2, 0.4, 0.8, 1.0], dtype=np.float64)
        for label in ("relevance", "utilization", "completeness")
    }
    compact = CompactDataset(
        ids=tuple(f"row-{index}" for index in range(row_count)),
        subsets=("covidqa",) * row_count,
        splits=splits,
        lexical_features=np.zeros((row_count, 1), dtype=np.float64),
        lexical_scores={},
        adherence=adherence,
        continuous=continuous,
        published={field: values.copy() for field in PUBLISHED_TARGETS},
    )
    masks = {
        "train": np.zeros(row_count, dtype=np.bool_),
        "validation": np.asarray([value == "validation" for value in splits]),
        "test": np.asarray([value == "test" for value in splits]),
    }

    result = evaluate_published_scorers(compact=compact, masks=masks)

    faithfulness = result["ragas_faithfulness"]
    assert faithfulness["validation_count"] == 0
    assert faithfulness["test_count"] == 3
    assert faithfulness["test_out_of_range"] == 1
    assert faithfulness["metrics"]["threshold"] == 0.5
    assert faithfulness["metrics"]["threshold_source"] == "fixed_0.5_no_validation_values"
    assert result["ragas_context_relevance"]["metrics"]["count"] == 3
