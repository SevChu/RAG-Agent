import json
from pathlib import Path

import numpy as np
import pytest

import scripts.run_retrieval_benchmark as retrieval_benchmark
from app.evaluation.benchmark import CorpusDocument, RelevanceJudgment
from app.evaluation.experiments import OptimizationSplit, load_experiment_registry
from app.evaluation.retrieval import (
    Bm25Index,
    RetrievalHit,
    evaluate_retrieval,
    read_trec_run,
    reciprocal_rank_fusion,
    tokenize_for_bm25,
    write_trec_run,
)
from scripts.run_retrieval_benchmark import (
    WEEK6_DAY2_EXPERIMENT_ID,
    build_retrieval_slice_report,
    exact_dense_search,
    paired_bootstrap_delta,
    resolve_experiment_request,
    resolve_methods,
    verify_frozen_dataset,
)

_EXPERIMENT_REGISTRY = (
    Path(__file__).resolve().parents[1] / "app" / "evaluation" / "experiment-registry.json"
)


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


def test_dense_rerank_requires_registered_experiment_and_dense_dependency() -> None:
    with pytest.raises(ValueError, match="registered Week 6 Day 2"):
        resolve_methods(("dense-rerank",), set(), experiment_id=None)

    methods = resolve_methods(
        ("dense-rerank",),
        set(),
        experiment_id=WEEK6_DAY2_EXPERIMENT_ID,
    )

    assert methods == ("dense-rerank", "dense")


def test_week6_experiment_maps_dev_to_validation_and_rejects_test() -> None:
    experiment, split = resolve_experiment_request(
        WEEK6_DAY2_EXPERIMENT_ID,
        "dev",
        _EXPERIMENT_REGISTRY,
    )

    assert experiment is not None
    assert split is not None
    assert split.value == "validation"

    with pytest.raises(ValueError, match="requires later user approval"):
        resolve_experiment_request(
            WEEK6_DAY2_EXPERIMENT_ID,
            "test",
            _EXPERIMENT_REGISTRY,
        )


def test_registered_validation_verification_does_not_read_other_qrels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_root = tmp_path / "fiqa"
    dataset_root.mkdir()
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "beir-fiqa-2018",
        "lifecycle": "frozen",
        "source_url": "https://example.test/fiqa.zip",
        "archive_md5": "a" * 32,
        "archive_sha256": "b" * 64,
        "archive_bytes": 1,
        "files": {
            "corpus.jsonl": "1" * 64,
            "queries.jsonl": "2" * 64,
            "qrels/train.tsv": "3" * 64,
            "qrels/dev.tsv": "4" * 64,
            "qrels/test.tsv": "5" * 64,
        },
        "split_counts": {},
    }
    (dataset_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    visited: list[str] = []
    expected = manifest["files"]

    def fake_hash_file(path: Path) -> str:
        relative = path.relative_to(dataset_root / "raw").as_posix()
        visited.append(relative)
        return expected[relative]

    monkeypatch.setattr(retrieval_benchmark, "hash_file", fake_hash_file)

    verify_frozen_dataset(dataset_root, allowed_splits={"dev"})

    assert visited == ["corpus.jsonl", "queries.jsonl", "qrels/dev.tsv"]
    assert "qrels/train.tsv" not in visited
    assert "qrels/test.tsv" not in visited


def test_paired_bootstrap_is_deterministic_and_keeps_only_counts() -> None:
    result = paired_bootstrap_delta(
        [0.0, 1.0, 0.0],
        [1.0, 0.0, 0.0],
        seed=42,
        resamples=100,
    )

    assert result["mean_delta"] == pytest.approx(0.0)
    assert result["wins"] == 1
    assert result["ties"] == 1
    assert result["losses"] == 1
    assert result["query_count"] == 3


def test_retrieval_slice_report_contains_only_aggregate_payload() -> None:
    experiment = load_experiment_registry(_EXPERIMENT_REGISTRY).get(
        WEEK6_DAY2_EXPERIMENT_ID
    )
    run = {"q-private": (RetrievalHit("d1", 1.0), RetrievalHit("d2", 0.5))}
    method_result = {
        "metrics": {"ndcg@10": 1.0, "recall@100": 1.0, "mrr@10": 1.0},
        "query_count": 1,
        "wall_seconds": 0.1,
        "resources": {"gpu_peak_allocated_bytes": 0},
        "latency": {"mean_ms": 1.0},
        "run_sha256": "a" * 64,
    }

    report = build_retrieval_slice_report(
        experiment=experiment,
        optimization_split=OptimizationSplit.VALIDATION,
        source_split="dev",
        query_texts={"q-private": "private query text"},
        qrels=[RelevanceJudgment(query_id="q-private", corpus_id="d1", relevance=1)],
        runs={"dense": run},
        state={"experiments": {"dense": method_result}},
    )

    serialized = json.dumps(report, sort_keys=True)
    assert report["contains_sample_ids_or_text"] is False
    assert "q-private" not in serialized
    assert "private query text" not in serialized
    assert report["methods"]["dense"]["slices"]
