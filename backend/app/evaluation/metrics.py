from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from statistics import fmean
from typing import Any

from app.evaluation.dataset import EvaluationCase


def evaluate_response(case: EvaluationCase, response: Mapping[str, Any]) -> dict[str, Any]:
    answer = str(response.get("answer") or "")
    citations = _dict_items(response.get("citations"))
    retrieval = _mapping(response.get("retrieval"))
    external = _mapping(response.get("external_search"))
    expected = case.expected

    citation_labels = [_citation_label(item) for item in citations]
    matched_targets = [
        target
        for target in expected.source_targets
        if any(target.casefold() in label.casefold() for label in citation_labels)
    ]
    first_target_rank = next(
        (
            index
            for index, label in enumerate(citation_labels, start=1)
            if any(target.casefold() in label.casefold() for target in expected.source_targets)
        ),
        None,
    )
    forbidden_source_hits = [
        target
        for target in expected.forbidden_source_targets
        if any(target.casefold() in label.casefold() for label in citation_labels)
    ]
    forbidden_answer_hits = [
        term for term in expected.forbidden_answer_terms if term.casefold() in answer.casefold()
    ]
    covered_key_points = [
        point for point in expected.key_points if point.casefold() in answer.casefold()
    ]
    external_triggered = bool(external.get("triggered"))
    external_citation_count = sum(
        item.get("source_type") == "external" for item in citations
    )
    external_match = (
        expected.external_search == "optional"
        or (
            expected.external_search == "required"
            and external_triggered
            and external_citation_count > 0
        )
        or (expected.external_search == "forbidden" and not external_triggered)
    )
    citation_match = (
        bool(citations) if expected.requires_citations else not bool(citations)
    )
    exam_match = _exam_expectation_match(case, retrieval)
    structural_checks = {
        "status_match": response.get("status") == expected.status,
        "task_type_match": response.get("task_type") == expected.task_type,
        "scope_match": response.get("answer_scope") == case.answer_scope,
        "citation_requirement_match": citation_match,
        "external_search_match": external_match,
        "exam_contract_match": exam_match,
        "forbidden_source_count": len(forbidden_source_hits),
        "forbidden_answer_term_count": len(forbidden_answer_hits),
    }
    structural_pass = (
        all(value for key, value in structural_checks.items() if key.endswith("_match"))
        and not forbidden_source_hits
        and not forbidden_answer_hits
    )
    return {
        **structural_checks,
        "structural_pass": structural_pass,
        "citation_count": len(citations),
        "course_citation_count": sum(item.get("source_type") == "course" for item in citations),
        "external_citation_count": external_citation_count,
        "source_target_recall": (
            len(matched_targets) / len(expected.source_targets)
            if expected.source_targets
            else None
        ),
        "source_target_mrr": (
            1 / first_target_rank
            if first_target_rank
            else (0.0 if expected.source_targets else None)
        ),
        "matched_source_targets": matched_targets,
        "forbidden_source_hits": forbidden_source_hits,
        "key_point_lexical_recall": (
            len(covered_key_points) / len(expected.key_points)
            if expected.key_points
            else None
        ),
        "covered_key_points": covered_key_points,
        "forbidden_answer_hits": forbidden_answer_hits,
        "context_message_count": int(retrieval.get("context_message_count") or 0),
        "answer_chars": len(answer),
        "elapsed_ms": float(response.get("elapsed_ms") or 0),
        "reported_tokens": int(_mapping(response.get("usage")).get("total_tokens") or 0),
        "human_review": None,
        "llm_judge": None,
    }


def aggregate_results(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    completed = [row for row in rows if row.get("execution_status") == "completed"]
    metrics = [_mapping(row.get("metrics")) for row in completed]
    latencies = [float(item.get("elapsed_ms") or 0) for item in metrics]
    token_total = sum(int(item.get("reported_tokens") or 0) for item in metrics)
    return {
        "selected_case_count": len(rows),
        "completed_case_count": len(completed),
        "failed_case_count": sum(row.get("execution_status") == "failed" for row in rows),
        "structural_pass_rate": _rate(metrics, "structural_pass"),
        "status_accuracy": _rate(metrics, "status_match"),
        "task_type_accuracy": _rate(metrics, "task_type_match"),
        "citation_requirement_accuracy": _rate(metrics, "citation_requirement_match"),
        "mean_source_target_recall": _mean_optional(metrics, "source_target_recall"),
        "mean_source_target_mrr": _mean_optional(metrics, "source_target_mrr"),
        "mean_key_point_lexical_recall": _mean_optional(
            metrics, "key_point_lexical_recall"
        ),
        "cross_course_source_leak_count": sum(
            int(item.get("forbidden_source_count") or 0) for item in metrics
        ),
        "mean_elapsed_ms": fmean(latencies) if latencies else None,
        "p95_elapsed_ms": _percentile(latencies, 0.95),
        "response_reported_token_total": token_total,
        "human_reviewed_count": sum(
            isinstance(row.get("human_review"), dict)
            and row["human_review"].get("review_status") == "verified"
            for row in completed
        ),
        "llm_judged_count": sum(
            isinstance(row.get("llm_judge"), dict) for row in completed
        ),
    }


def _exam_expectation_match(case: EvaluationCase, retrieval: Mapping[str, Any]) -> bool:
    expected = case.expected
    if expected.task_type != "exam":
        return True
    plan = _mapping(retrieval.get("exam_plan"))
    quality = _mapping(retrieval.get("exam_quality"))
    return (
        plan.get("question_count") == expected.question_count
        and plan.get("include_answers") is expected.include_answers
        and plan.get("include_explanations") is expected.include_explanations
        and quality.get("generated_question_count") == expected.question_count
        and bool(quality.get("citations_valid"))
        and bool(quality.get("source_limits_passed"))
    )


def _citation_label(citation: Mapping[str, Any]) -> str:
    return " | ".join(
        [
            str(citation.get("file_name") or ""),
            " > ".join(str(item) for item in citation.get("section_path") or []),
            str(citation.get("title") or ""),
            str(citation.get("publisher") or ""),
        ]
    )


def _dict_items(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _rate(rows: list[Mapping[str, Any]], key: str) -> float | None:
    return fmean(bool(row.get(key)) for row in rows) if rows else None


def _mean_optional(rows: list[Mapping[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return fmean(values) if values else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]
