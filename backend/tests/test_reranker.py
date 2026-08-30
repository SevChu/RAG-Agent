from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from app.knowledge import VectorSearchResult
from app.retrieval import (
    BgeReranker,
    DenseRetrievalResult,
    expand_query_terms,
    matches_query_concepts,
)


class FakeCrossEncoder:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, inputs: list[tuple[str, str]], **kwargs: Any) -> np.ndarray:
        self.calls.append(inputs)
        return np.asarray(self.scores, dtype=np.float32)


def _hit(
    point_id: str,
    *,
    dense_score: float,
    text: str,
    section: str,
) -> VectorSearchResult:
    return VectorSearchResult(
        point_id=point_id,
        score=dense_score,
        course_id="course-1",
        document_id="document-1",
        chunk_index=int(point_id[-1]),
        text=text,
        payload={
            "file_name": "数据结构.pdf",
            "section_path": [section],
            "block_kinds": ["paragraph"],
        },
    )


def test_reranker_reorders_candidates_and_rejects_unanswered_questions(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "reranker"
    model_path.mkdir()
    model = FakeCrossEncoder([0.2, 4.0, 8.0])
    reranker = BgeReranker(
        model_path,
        device="cpu",
        model_factory=lambda _path, _device, _length: model,
    )
    dense = DenseRetrievalResult(
        query="栈和队列有什么区别？",
        hits=(
            _hit(
                "point-1",
                dense_score=0.91,
                text="图可以采用邻接矩阵存储。",
                section="图",
            ),
            _hit(
                "point-2",
                dense_score=0.72,
                text="栈后进先出，队列先进先出。",
                section="栈和队列",
            ),
            _hit(
                "point-3",
                dense_score=0.99,
                text="队列是一种先进后出的线性表（ ）。",
                section="判断题",
            ),
        ),
        embedding_device="cpu",
    )

    result = reranker.rerank(dense, top_k=2)

    assert [hit.point_id for hit in result.hits] == ["point-2"]
    assert result.dense_candidate_count == 3
    assert result.rejected_evidence_count == 2
    assert result.reranker_device == "cpu"
    assert result.hits[0].payload["dense_score"] == 0.72
    assert result.hits[0].payload["content_role"] == "exposition"
    assert result.hits[0].score > 0.9


def test_reranker_skips_model_for_empty_candidates(tmp_path: Path) -> None:
    model_path = tmp_path / "reranker"
    model_path.mkdir()
    model = FakeCrossEncoder([])
    reranker = BgeReranker(
        model_path,
        device="cpu",
        model_factory=lambda _path, _device, _length: model,
    )

    result = reranker.rerank(
        DenseRetrievalResult(
            query="超出课程的问题",
            hits=(),
            embedding_device=None,
        ),
        top_k=6,
    )

    assert result.hits == ()
    assert result.reranker_device is None
    assert model.calls == []


def test_exam_rerank_can_retain_exercise_questions_without_changing_qa_default(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "reranker"
    model_path.mkdir()
    model = FakeCrossEncoder([4.0])
    reranker = BgeReranker(
        model_path,
        device="cpu",
        model_factory=lambda _path, _device, _length: model,
    )
    dense = DenseRetrievalResult(
        query="队列练习题",
        hits=(
            _hit(
                "point-1",
                dense_score=0.9,
                text="队列是一种先进先出的线性表（ ）。",
                section="判断题",
            ),
        ),
        embedding_device="cpu",
    )

    qa_result = reranker.rerank(dense, top_k=1)
    exam_result = reranker.rerank(
        dense,
        top_k=1,
        allow_exercise_questions=True,
    )

    assert qa_result.hits == ()
    assert exam_result.hits[0].payload["content_role"] == "exercise_question"
    assert exam_result.hits[0].payload["evidence_eligible"] is True


def test_query_term_expansion_is_small_and_deterministic() -> None:
    assert expand_query_terms("二分查找的适用条件") == ("二分查找的适用条件\n相关术语：折半查找")
    assert expand_query_terms("二分查找也叫折半查找") == "二分查找也叫折半查找"


def test_explicit_concept_anchor_rejects_obvious_topic_drift() -> None:
    assert matches_query_concepts("队列是先进先出吗？", "循环队列在队尾入队。")
    assert not matches_query_concepts("队列是先进先出吗？", "栈遵循后进先出。")
    assert matches_query_concepts("二分查找复杂度", "折半查找要求有序表。")
    assert matches_query_concepts("一般如何衡量算法？", "时间复杂度是一种指标。")


def test_reranker_can_score_generic_passages_without_evidence_gates(tmp_path: Path) -> None:
    model_path = tmp_path / "reranker"
    model_path.mkdir()
    model = FakeCrossEncoder([0.0, 2.0])
    reranker = BgeReranker(
        model_path,
        device="cpu",
        model_factory=lambda _path, _device, _length: model,
    )

    scores = reranker.score_passages("financial query", ["first passage", "second passage"])

    assert scores[0] == 0.5
    assert scores[1] > scores[0]
    assert model.calls == [
        [("financial query", "first passage"), ("financial query", "second passage")]
    ]
    assert reranker.score_passages("financial query", []) == ()
