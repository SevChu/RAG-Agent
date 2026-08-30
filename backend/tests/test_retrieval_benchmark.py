from pathlib import Path

import numpy as np
import pytest

from app.evaluation.benchmark import CorpusDocument, RelevanceJudgment
from app.evaluation.retrieval import (
    Bm25Index,
    RetrievalHit,
    evaluate_retrieval,
    read_trec_run,
    reciprocal_rank_fusion,
    tokenize_for_bm25,
    write_trec_run,
)
from scripts.run_retrieval_benchmark import exact_dense_search


def test_bm25_tokenization_and_ranking_are_deterministic() -> None:
    assert tokenize_for_bm25("Why isn't ROE 12.5%?") == ("why", "isn't", "roe", "12.5")
    index = Bm25Index(
        [
            CorpusDocument(id="d1", title="Return on equity", text="ROE measures profit."),
            CorpusDocument(id="d2", title="Cash flow", text="Cash from operations."),
            CorpusDocument(id="d3", title="", text=""),
        ]
    )

    hits = index.search("ROE profit", top_k=2)

    assert [hit.document_id for hit in hits] == ["d1"]
    assert hits[0].score > 0


def test_reciprocal_rank_fusion_uses_ranks_instead_of_raw_scores() -> None:
    fused = reciprocal_rank_fusion(
        [
            [RetrievalHit("a", 100.0), RetrievalHit("b", 90.0)],
            [RetrievalHit("b", 0.9), RetrievalHit("c", 0.8)],
        ],
        top_k=3,
        rank_constant=60,
    )

    assert [hit.document_id for hit in fused] == ["b", "a", "c"]


def test_retrieval_metrics_include_all_requested_families() -> None:
    qrels = [
        RelevanceJudgment(query_id="q1", corpus_id="d1", relevance=1),
        RelevanceJudgment(query_id="q1", corpus_id="d2", relevance=1),
        RelevanceJudgment(query_id="q2", corpus_id="d3", relevance=1),
    ]
    run = {
        "q1": [RetrievalHit("d1", 2), RetrievalHit("x", 1)],
        "q2": [],
    }

    result = evaluate_retrieval(run, qrels, ks=(1, 2))

    assert result.query_count == 2
    assert result.values["precision@1"] == pytest.approx(0.5)
    assert result.values["recall@2"] == pytest.approx(0.25)
    assert result.values["mrr@2"] == pytest.approx(0.5)
    assert result.values["map@2"] == pytest.approx(0.25)
    assert result.values["ndcg@2"] > 0


def test_trec_run_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "bm25.run"
    original = {
        "q2": [RetrievalHit("d2", 0.2)],
        "q1": [RetrievalHit("d1", 0.9), RetrievalHit("d3", 0.1)],
    }

    write_trec_run(path, original, run_name="agentic-bm25")

    loaded = read_trec_run(path)
    assert list(loaded) == ["q1", "q2"]
    assert loaded == {query_id: tuple(hits) for query_id, hits in original.items()}


def test_exact_dense_search_ranks_normalized_vectors_on_cpu() -> None:
    corpus = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.7, 0.7],
        ],
        dtype=np.float32,
    )
    query = np.asarray([[1.0, 0.0]], dtype=np.float32)

    run, latencies, device = exact_dense_search(
        corpus, ["d1", "d2", "d3"], ["q1"], query, device="cpu"
    )

    assert [hit.document_id for hit in run["q1"]] == ["d1", "d3", "d2"]
    assert len(latencies) == 1
    assert device == "cpu"
