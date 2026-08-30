from __future__ import annotations

import pytest

from app.evaluation import (
    add_char_confusion,
    binary_metrics,
    char_labels,
    context_chunks,
    expected_calibration_error,
    lexical_feature_vector,
    metrics_from_confusion,
    predicted_char_labels,
    sentence_spans,
    split_train_dev_sources,
    tokenize,
)


def test_sentence_spans_preserve_response_offsets() -> None:
    text = "Paris is supported. London is not.\nA final claim"

    spans = sentence_spans(text)

    assert [item.text for item in spans] == [
        "Paris is supported.",
        "London is not.",
        "A final claim",
    ]
    assert [text[item.start : item.end] for item in spans] == [item.text for item in spans]


def test_lexical_features_surface_unsupported_facts() -> None:
    context = "Paris has a population of 2 million people and is in France."

    supported = lexical_feature_vector(context, "Paris has a population of 2 million.")
    unsupported = lexical_feature_vector(context, "London has a population of 9 million.")

    assert supported[0] > unsupported[0]
    assert supported[1] > unsupported[1]
    assert supported[3] < unsupported[3]
    assert supported[4] < unsupported[4]
    assert tokenize("BGE-M3 isn't lexical-only") == ("bge-m3", "isn't", "lexical-only")


def test_context_chunks_are_bounded_and_overlap_long_text() -> None:
    chunks = context_chunks("x" * 260, max_chars=100, overlap_chars=20)

    assert len(chunks) == 4
    assert all(0 < len(item) <= 100 for item in chunks)
    assert chunks[0][-20:] == chunks[1][:20]


def test_train_dev_split_is_deterministic_and_task_stratified() -> None:
    sources = {
        **{f"qa-{index}": "QA" for index in range(10)},
        **{f"summary-{index}": "Summary" for index in range(10)},
    }

    first = split_train_dev_sources(sources, seed=42, dev_fraction=0.2)
    second = split_train_dev_sources(sources, seed=42, dev_fraction=0.2)

    assert first == second
    assert len(first) == 4
    assert sum(item.startswith("qa-") for item in first) == 2
    assert sum(item.startswith("summary-") for item in first) == 2


def test_response_and_char_metrics_use_positive_hallucination_class() -> None:
    response = binary_metrics([1, 1, 0, 0], [1, 0, 1, 0])

    assert response.precision == pytest.approx(0.5)
    assert response.recall == pytest.approx(0.5)
    assert response.f1 == pytest.approx(0.5)

    text = "supported hallucinated"
    gold = char_labels(
        len(text),
        [{"start": 10, "end": 22, "text": "hallucinated"}],
    )
    predicted = predicted_char_labels(len(text), [sentence_spans(text)[0]])
    counts = [0, 0, 0, 0]
    add_char_confusion(counts, gold, predicted)
    span = metrics_from_confusion(counts)

    assert span.recall == pytest.approx(1.0)
    assert span.precision == pytest.approx(12 / 22)


def test_expected_calibration_error_rejects_mismatched_inputs() -> None:
    assert expected_calibration_error([0, 1], [0.1, 0.9], bins=2) == pytest.approx(0.1)
    with pytest.raises(ValueError, match="equal non-empty"):
        expected_calibration_error([1], [], bins=10)
