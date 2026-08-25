from __future__ import annotations

from pathlib import Path

import pytest

from app.evaluation import (
    EvaluationDataset,
    EvaluationRunStore,
    HumanAnnotationFile,
    JudgeResultFile,
    aggregate_results,
    dataset_summary,
    evaluate_response,
    load_evaluation_dataset,
    merge_review_layers,
)
from scripts.run_week5_evaluation import _should_run_case

_DATASET = Path(__file__).resolve().parents[1] / "evaluations" / "week05" / "dataset-v1.json"


def test_week_five_dataset_has_frozen_distribution_and_isolated_partitions() -> None:
    dataset, digest = load_evaluation_dataset(_DATASET)

    assert len(digest) == 64
    assert dataset.baseline.git_commit == "d1dfc33"
    assert dataset.baseline.context_max_messages == 6
    assert dataset.baseline.context_max_chars == 6000
    assert dataset_summary(dataset) == {
        "dataset_id": "week05-data-structures-100",
        "version": "2026-08-10.1",
        "case_count": 100,
        "split_counts": {"train": 60, "validation": 20, "test": 20},
        "category_counts": {
            "course_qa": 25,
            "refusal": 10,
            "mixed_source": 15,
            "dynamic_summary": 10,
            "mixed_exam": 10,
            "multi_turn": 20,
            "course_isolation": 10,
        },
        "annotation_counts": {"candidate": 100, "verified": 0},
        "partition_count": 49,
    }


def test_dataset_rejects_a_partition_that_crosses_splits() -> None:
    dataset, _ = load_evaluation_dataset(_DATASET)
    payload = dataset.model_dump(mode="json")
    payload["cases"][1]["partition_key"] = payload["cases"][0]["partition_key"]
    payload["cases"][1]["split"] = "validation"

    with pytest.raises(ValueError, match="crosses"):
        EvaluationDataset.model_validate(payload)


def test_metrics_keep_deterministic_human_and_judge_layers_separate() -> None:
    dataset, _ = load_evaluation_dataset(_DATASET)
    case = next(item for item in dataset.cases if item.id == "W5-037")
    response = {
        "answer": "栈遵循 LIFO，并由底层容器提供操作，所以 std::stack 是适配器。",
        "status": "answered",
        "task_type": "question",
        "answer_scope": "course_and_external",
        "elapsed_ms": 12.5,
        "usage": {"total_tokens": 42},
        "external_search": {"triggered": True},
        "retrieval": {"context_message_count": 0},
        "citations": [
            {
                "source_type": "course",
                "file_name": "数据结构_C++实现  第2版.pdf",
                "section_path": ["栈"],
            },
            {
                "source_type": "external",
                "title": "std::stack",
                "publisher": "C++ reference",
            },
        ],
    }

    metrics = evaluate_response(case, response)

    assert metrics["structural_pass"] is True
    assert metrics["external_citation_count"] == 1
    assert metrics["source_target_recall"] == 1
    assert metrics["human_review"] is None
    assert metrics["llm_judge"] is None
    aggregate = aggregate_results(
        [{"execution_status": "completed", "metrics": metrics}]
    )
    assert aggregate["completed_case_count"] == 1
    assert aggregate["human_reviewed_count"] == 0
    assert aggregate["llm_judged_count"] == 0


def test_run_store_resumes_completed_cases_without_changing_identity(
    tmp_path: Path,
) -> None:
    store = EvaluationRunStore(tmp_path / "run")
    identity = {"dataset_sha256": "abc", "model": "test"}

    first_state = store.initialize(identity)
    store.write_case_result(
        "W5-001",
        {"case_id": "W5-001", "execution_status": "completed"},
    )
    resumed_state = EvaluationRunStore(tmp_path / "run").initialize(identity)

    assert resumed_state["created_at"] == first_state["created_at"]
    assert store.result("W5-001") == {
        "case_id": "W5-001",
        "execution_status": "completed",
    }
    with pytest.raises(ValueError, match="different dataset"):
        store.initialize({"dataset_sha256": "changed", "model": "test"})


def test_human_and_judge_reviews_remain_separate_layers() -> None:
    human = HumanAnnotationFile.model_validate(
        {
            "schema_version": "1.0",
            "dataset_id": "dataset",
            "dataset_version": "1",
            "dataset_sha256": "a" * 64,
            "instructions": "test",
            "cases": [
                {
                    "case_id": "W5-001",
                    "review_status": "verified",
                    "reference_answer": "人工答案",
                    "reviewer": "reviewer",
                }
            ],
        }
    )
    judge = JudgeResultFile.model_validate(
        {
            "schema_version": "1.0",
            "dataset_sha256": "a" * 64,
            "judge_model": "judge",
            "judge_prompt_version": "v1",
            "generated_at": "2026-08-10T00:00:00Z",
            "cases": [
                {
                    "case_id": "W5-001",
                    "verdict": "fail",
                    "scores": {"faithfulness": 0.1},
                    "rationale": "辅助意见",
                }
            ],
        }
    )

    merged = merge_review_layers(
        [
            {
                "case_id": "W5-001",
                "execution_status": "completed",
                "metrics": {"structural_pass": True},
            }
        ],
        human=human,
        judge=judge,
    )

    assert merged[0]["human_review"]["reference_answer"] == "人工答案"
    assert merged[0]["llm_judge"]["verdict"] == "fail"
    aggregate = aggregate_results(merged)
    assert aggregate["human_reviewed_count"] == 1
    assert aggregate["llm_judged_count"] == 1


def test_completed_cases_are_never_selected_for_a_paid_rerun() -> None:
    assert _should_run_case(None, rerun_failed=False) is True
    assert (
        _should_run_case(
            {"execution_status": "completed"},
            rerun_failed=True,
        )
        is False
    )
    assert (
        _should_run_case(
            {"execution_status": "failed"},
            rerun_failed=False,
        )
        is False
    )
    assert (
        _should_run_case(
            {"execution_status": "failed"},
            rerun_failed=True,
        )
        is True
    )
