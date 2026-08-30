from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Hashable, Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from typing import TypeVar

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*")
_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*(?:%|st|nd|rd|th)?", re.IGNORECASE)
_CAPITALIZED_RE = re.compile(r"\b[A-Z][A-Za-z0-9'-]+\b")
_SENTENCE_RE = re.compile(r"\S(?:.*?)(?:[.!?](?=\s|$)|\n+|$)", re.DOTALL)
_NEGATIONS = frozenset({"no", "not", "never", "none", "neither", "nor", "without", "cannot"})
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "i",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "she",
        "that",
        "the",
        "their",
        "there",
        "they",
        "this",
        "to",
        "was",
        "were",
        "which",
        "who",
        "will",
        "with",
        "you",
    }
)

LEXICAL_FEATURE_NAMES = (
    "token_coverage",
    "content_token_coverage",
    "bigram_coverage",
    "unsupported_number_ratio",
    "unsupported_capitalized_ratio",
    "negation_mismatch",
    "response_token_length",
    "context_token_length",
)


@dataclass(frozen=True, slots=True)
class TextSpan:
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class BinaryMetrics:
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int


@dataclass(frozen=True, slots=True)
class LexicalContext:
    token_count: int
    tokens: frozenset[str]
    bigrams: frozenset[tuple[str, str]]
    numbers: frozenset[str]
    capitalized: frozenset[str]
    negations: frozenset[str]


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).lower() for match in _TOKEN_RE.finditer(text))


def sentence_spans(text: str) -> tuple[TextSpan, ...]:
    spans: list[TextSpan] = []
    for match in _SENTENCE_RE.finditer(text):
        start = match.start()
        end = match.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append(TextSpan(start=start, end=end, text=text[start:end]))
    if not spans and text.strip():
        start = len(text) - len(text.lstrip())
        end = len(text.rstrip())
        spans.append(TextSpan(start=start, end=end, text=text[start:end]))
    return tuple(spans)


def context_chunks(
    text: str, *, max_chars: int = 1200, overlap_chars: int = 120
) -> tuple[str, ...]:
    if max_chars < 100:
        raise ValueError("context chunk size must be at least 100 characters")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("context chunk overlap must be non-negative and smaller than max_chars")
    chunks: list[str] = []
    current = ""
    for span in sentence_spans(text):
        sentence = span.text.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            step = max_chars - overlap_chars
            chunks.extend(
                sentence[start : start + max_chars]
                for start in range(0, len(sentence), step)
                if sentence[start : start + max_chars].strip()
            )
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return tuple(chunks or (text.strip(),))


def build_lexical_context(context: str) -> LexicalContext:
    context_tokens = tokenize(context)
    return LexicalContext(
        token_count=len(context_tokens),
        tokens=frozenset(context_tokens),
        bigrams=frozenset(zip(context_tokens, context_tokens[1:], strict=False)),
        numbers=frozenset(_normalize_surface(item) for item in _NUMBER_RE.findall(context)),
        capitalized=frozenset(
            _normalize_surface(item) for item in _CAPITALIZED_RE.findall(context)
        ),
        negations=frozenset(set(context_tokens).intersection(_NEGATIONS)),
    )


def lexical_feature_vector(
    context: str | LexicalContext,
    response_sentence: str,
) -> tuple[float, ...]:
    prepared = build_lexical_context(context) if isinstance(context, str) else context
    response_tokens = tokenize(response_sentence)
    token_coverage = _coverage(response_tokens, prepared.tokens)

    content_tokens = tuple(token for token in response_tokens if token not in _STOPWORDS)
    content_coverage = _coverage(content_tokens, prepared.tokens)

    response_bigrams = tuple(zip(response_tokens, response_tokens[1:], strict=False))
    bigram_coverage = _coverage(response_bigrams, prepared.bigrams)

    response_numbers = tuple(
        _normalize_surface(item) for item in _NUMBER_RE.findall(response_sentence)
    )
    unsupported_number_ratio = 1.0 - _coverage(response_numbers, prepared.numbers)

    response_capitalized = tuple(
        _normalize_surface(item) for item in _CAPITALIZED_RE.findall(response_sentence)
    )
    unsupported_capitalized_ratio = 1.0 - _coverage(
        response_capitalized,
        prepared.capitalized,
    )

    response_negations = set(response_tokens).intersection(_NEGATIONS)
    negation_mismatch = float(bool(response_negations.difference(prepared.negations)))

    return (
        token_coverage,
        content_coverage,
        bigram_coverage,
        unsupported_number_ratio,
        unsupported_capitalized_ratio,
        negation_mismatch,
        min(1.0, math.log1p(len(response_tokens)) / math.log(101.0)),
        min(1.0, math.log1p(prepared.token_count) / math.log(5001.0)),
    )


def split_train_dev_sources(
    source_tasks: Mapping[str, str],
    *,
    seed: int = 42,
    dev_fraction: float = 0.2,
) -> frozenset[str]:
    if not 0.0 < dev_fraction < 1.0:
        raise ValueError("dev fraction must be between zero and one")
    by_task: dict[str, list[str]] = {}
    for source_id, task in source_tasks.items():
        by_task.setdefault(task, []).append(source_id)
    selected: set[str] = set()
    for task, source_ids in sorted(by_task.items()):
        ranked = sorted(
            source_ids,
            key=lambda source_id: hashlib.sha256(f"{seed}:{task}:{source_id}".encode()).hexdigest(),
        )
        count = max(1, round(len(ranked) * dev_fraction))
        selected.update(ranked[:count])
    return frozenset(selected)


def binary_metrics(labels: Sequence[int], predictions: Sequence[int]) -> BinaryMetrics:
    if len(labels) != len(predictions) or not labels:
        raise ValueError("binary metrics require equal non-empty inputs")
    tp = sum(
        label == 1 and prediction == 1
        for label, prediction in zip(labels, predictions, strict=True)
    )
    fp = sum(
        label == 0 and prediction == 1
        for label, prediction in zip(labels, predictions, strict=True)
    )
    fn = sum(
        label == 1 and prediction == 0
        for label, prediction in zip(labels, predictions, strict=True)
    )
    tn = sum(
        label == 0 and prediction == 0
        for label, prediction in zip(labels, predictions, strict=True)
    )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return BinaryMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
    )


def char_labels(length: int, labels: Iterable[Mapping[str, object]]) -> bytearray:
    mask = bytearray(length)
    for label in labels:
        start_value = label["start"]
        end_value = label["end"]
        if not isinstance(start_value, int) or not isinstance(end_value, int):
            raise ValueError("char labels require integer offsets")
        start = start_value
        end = end_value
        mask[start:end] = b"\x01" * (end - start)
    return mask


def predicted_char_labels(length: int, spans: Iterable[TextSpan]) -> bytearray:
    mask = bytearray(length)
    for span in spans:
        mask[span.start : span.end] = b"\x01" * (span.end - span.start)
    return mask


def add_char_confusion(
    counts: list[int],
    expected: bytearray,
    predicted: bytearray,
) -> None:
    if len(counts) != 4 or len(expected) != len(predicted):
        raise ValueError("invalid char confusion inputs")
    for label, prediction in zip(expected, predicted, strict=True):
        if label and prediction:
            counts[0] += 1
        elif not label and prediction:
            counts[1] += 1
        elif label and not prediction:
            counts[2] += 1
        else:
            counts[3] += 1


def metrics_from_confusion(counts: Sequence[int]) -> BinaryMetrics:
    if len(counts) != 4:
        raise ValueError("confusion counts must contain tp, fp, fn and tn")
    tp, fp, fn, tn = (int(value) for value in counts)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return BinaryMetrics(precision, recall, f1, tp, fp, fn, tn)


def expected_calibration_error(
    labels: Sequence[int],
    scores: Sequence[float],
    *,
    bins: int = 10,
) -> float:
    if len(labels) != len(scores) or not labels:
        raise ValueError("calibration error requires equal non-empty inputs")
    if bins < 2:
        raise ValueError("calibration error requires at least two bins")
    total = len(labels)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            position
            for position, score in enumerate(scores)
            if lower <= score < upper or (index == bins - 1 and score == 1.0)
        ]
        if not members:
            continue
        confidence = sum(scores[position] for position in members) / len(members)
        accuracy = sum(labels[position] for position in members) / len(members)
        error += len(members) / total * abs(confidence - accuracy)
    return error


CoverageItem = TypeVar("CoverageItem", bound=Hashable)


def _coverage(items: Sequence[CoverageItem], supported: Set[CoverageItem]) -> float:
    if not items:
        return 1.0
    return sum(item in supported for item in items) / len(items)


def _normalize_surface(value: str) -> str:
    return value.casefold().replace(",", "")
