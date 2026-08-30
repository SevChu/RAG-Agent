from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from app.evaluation.hallucination import binary_metrics, lexical_feature_vector

TRACE_LABELS: Final = ("adherence", "relevance", "utilization", "completeness")
LEXICAL_FEATURE_NAMES: Final = tuple(
    f"{prefix}_{name}"
    for prefix in ("response_context", "question_context", "response_question")
    for name in (
        "token_coverage",
        "content_token_coverage",
        "bigram_coverage",
        "unsupported_number_ratio",
        "unsupported_capitalized_ratio",
        "negation_mismatch",
        "first_text_length",
        "second_text_length",
    )
) + ("document_count",)


@dataclass(frozen=True)
class ContinuousMetrics:
    count: int
    mae: float
    rmse: float
    pearson: float
    spearman: float


def ragbench_lexical_features(
    *,
    question: str,
    documents: tuple[str, ...],
    response: str,
) -> tuple[float, ...]:
    context = "\n\n".join(documents)
    return (
        *lexical_feature_vector(context, response),
        *lexical_feature_vector(context, question),
        *lexical_feature_vector(question, response),
        min(1.0, math.log1p(len(documents)) / math.log(33.0)),
    )


def lexical_trace_scores(features: tuple[float, ...]) -> dict[str, float]:
    if len(features) != len(LEXICAL_FEATURE_NAMES):
        raise ValueError("unexpected RAGBench lexical feature count")
    response_context = features[0:8]
    question_context = features[8:16]
    response_question = features[16:24]
    adherence = _mean(
        (
            response_context[0],
            response_context[1],
            response_context[2],
            1.0 - response_context[3],
            1.0 - response_context[4],
            1.0 - response_context[5],
        )
    )
    relevance = _mean(
        (
            question_context[0],
            question_context[1],
            question_context[2],
            1.0 - question_context[3],
            1.0 - question_context[4],
        )
    )
    utilization = _mean(
        (
            response_context[0],
            response_context[1],
            response_context[2],
        )
    )
    completeness = _mean(
        (
            response_question[0],
            response_question[1],
            response_context[1],
        )
    )
    return {
        "adherence": _clip_unit(adherence),
        "relevance": _clip_unit(relevance),
        "utilization": _clip_unit(utilization),
        "completeness": _clip_unit(completeness),
    }


def tune_binary_threshold(
    labels: list[int],
    scores: list[float],
    *,
    step: float = 0.005,
) -> float:
    if len(labels) != len(scores) or not labels:
        raise ValueError("labels and scores must have the same non-zero length")
    if not 0.0 < step <= 1.0:
        raise ValueError("step must be within (0, 1]")
    candidates = [round(index * step, 12) for index in range(round(1.0 / step) + 1)]
    best_threshold = 0.5
    best_key = (-1.0, -1.0, -1.0)
    for threshold in candidates:
        predictions = [int(score >= threshold) for score in scores]
        metrics = binary_metrics(labels, predictions)
        key = (metrics.f1, metrics.precision, threshold)
        if key > best_key:
            best_key = key
            best_threshold = threshold
    return best_threshold


def continuous_metrics(labels: list[float], predictions: list[float]) -> ContinuousMetrics:
    if len(labels) != len(predictions) or not labels:
        raise ValueError("labels and predictions must have the same non-zero length")
    errors = [prediction - label for label, prediction in zip(labels, predictions, strict=True)]
    return ContinuousMetrics(
        count=len(labels),
        mae=sum(abs(error) for error in errors) / len(errors),
        rmse=math.sqrt(sum(error * error for error in errors) / len(errors)),
        pearson=_pearson(labels, predictions),
        spearman=_pearson(_ranks(labels), _ranks(predictions)),
    )


def clip_predictions(values: list[float]) -> list[float]:
    return [_clip_unit(value) for value in values]


def _pearson(left: list[float], right: list[float]) -> float:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    numerator = sum(first * second for first, second in zip(left_delta, right_delta, strict=True))
    denominator = math.sqrt(
        sum(value * value for value in left_delta) * sum(value * value for value in right_delta)
    )
    return numerator / denominator if denominator else 0.0


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        for position in range(index, end):
            ranks[ordered[position][0]] = average_rank
        index = end
    return ranks


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values)


def _clip_unit(value: float) -> float:
    return min(1.0, max(0.0, value))
