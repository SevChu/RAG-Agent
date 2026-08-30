from __future__ import annotations

import json
import zipfile
from argparse import Namespace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.evaluation import (
    RAGBENCH_SPLITS,
    RAGBENCH_SUBSETS,
    BeirAdapter,
    BenchmarkLifecycle,
    BenchmarkTask,
    RagBenchAdapter,
    RagTruthAdapter,
    load_benchmark_registry,
)
from scripts.manage_benchmarks import _validated_members, download_dataset

_REGISTRY = Path(__file__).resolve().parents[1] / "app" / "evaluation" / "registry.json"


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


@pytest.fixture
def mini_beir(tmp_path: Path) -> Path:
    root = tmp_path / "beir"
    (root / "qrels").mkdir(parents=True)
    _write_jsonl(
        root / "corpus.jsonl",
        [
            {"_id": "d1", "title": "First", "text": "alpha", "metadata": {"source": "x"}},
            {"_id": "d2", "title": "", "text": "beta", "metadata": {}},
            {"_id": "d3", "title": "", "text": "", "metadata": {}},
        ],
    )
    _write_jsonl(
        root / "queries.jsonl",
        [
            {"_id": "q1", "text": "alpha question"},
            {"_id": "q2", "text": "beta question"},
        ],
    )
    (root / "qrels" / "test.tsv").write_text(
        "query-id\tcorpus-id\tscore\nq1\td1\t1\nq2\td2\t2\n",
        encoding="utf-8",
    )
    return root


def test_registry_tracks_only_explicitly_approved_datasets() -> None:
    registry, digest = load_benchmark_registry(_REGISTRY)

    assert len(digest) == 64
    assert registry.get("beir-fiqa-2018").lifecycle == BenchmarkLifecycle.APPROVED
    assert registry.get("beir-fiqa-2018").task == BenchmarkTask.RETRIEVAL
    assert registry.get("beir-fiqa-2018").expected_archive_md5 == (
        "17918ed23cd04fb15047f73e6c3bd9d9"
    )
    assert registry.get("beir-scifact").lifecycle == BenchmarkLifecycle.CANDIDATE
    assert {
        item.dataset_id
        for item in registry.datasets
        if item.lifecycle != BenchmarkLifecycle.CANDIDATE
    } == {"beir-fiqa-2018", "ragbench", "ragtruth"}
    ragtruth = registry.get("ragtruth")
    assert ragtruth.task == BenchmarkTask.HALLUCINATION_DETECTION
    assert ragtruth.source_revision == "c103204b9ce28d6bbad859304bf30de72b8ed8fe"
    assert set(ragtruth.download_files) == {"response.jsonl", "source_info.jsonl"}
    ragbench = registry.get("ragbench")
    assert ragbench.lifecycle == BenchmarkLifecycle.APPROVED
    assert ragbench.source_revision == "97808f3e5fd16ede40bbff6c2949af8139b2eb7b"
    assert ragbench.stats.response_count == 95381


def test_ragtruth_adapter_normalizes_and_validates_labels(tmp_path: Path) -> None:
    root = tmp_path / "ragtruth"
    root.mkdir()
    _write_jsonl(
        root / "source_info.jsonl",
        [
            {
                "source_id": "source-1",
                "task_type": "QA",
                "source": "MARCO",
                "source_info": {"question": "Where?", "passages": "The answer is Paris."},
                "prompt": "Answer from context.",
            }
        ],
    )
    _write_jsonl(
        root / "response.jsonl",
        [
            {
                "id": "response-1",
                "source_id": "source-1",
                "model": "example-model",
                "temperature": 0.0,
                "labels": [
                    {
                        "start": 14,
                        "end": 20,
                        "text": "London",
                        "label_type": "Evident Conflict",
                    }
                ],
                "split": "test",
                "quality": "good",
                "response": "The answer is London.",
            }
        ],
    )

    adapter = RagTruthAdapter(root)
    example = next(adapter.iter_examples("test"))

    assert example.response_id == "response-1"
    assert example.has_hallucination is True
    assert '"passages": "The answer is Paris."' in example.context
    assert adapter.validate(["test"]) == {
        "all": {
            "sources": 1,
            "responses": 1,
            "hallucinated_responses": 1,
            "spans": 1,
        },
        "test": {
            "sources": 1,
            "responses": 1,
            "hallucinated_responses": 1,
            "spans": 1,
        },
    }


def test_downloader_rejects_an_unapproved_candidate_before_network_access(
    tmp_path: Path,
) -> None:
    arguments = Namespace(
        registry=str(_REGISTRY),
        data_root=str(tmp_path),
        dataset="beir-scifact",
    )

    with pytest.raises(PermissionError, match="not approved"):
        download_dataset(arguments)

    assert list(tmp_path.iterdir()) == []


def test_beir_adapter_normalizes_corpus_queries_and_qrels(mini_beir: Path) -> None:
    adapter = BeirAdapter(mini_beir)

    corpus = tuple(adapter.iter_corpus())
    queries = adapter.queries("test")
    qrels = adapter.qrels("test")

    assert corpus[0].model_dump() == {
        "id": "d1",
        "title": "First",
        "text": "alpha",
        "metadata": {"source": "x"},
    }
    assert [(item.id, item.split) for item in queries] == [("q1", "test"), ("q2", "test")]
    assert [(item.query_id, item.corpus_id, item.relevance) for item in qrels] == [
        ("q1", "d1", 1.0),
        ("q2", "d2", 2.0),
    ]
    assert adapter.validate(["test"]) == {
        "test": {"queries": 2, "qrels": 2, "relevant_qrels": 2},
        "all": {"corpus": 3},
    }
    assert corpus[2].text == ""


def test_beir_adapter_rejects_qrels_for_unknown_documents(mini_beir: Path) -> None:
    (mini_beir / "qrels" / "test.tsv").write_text(
        "query-id\tcorpus-id\tscore\nq1\tmissing\t1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing corpus"):
        BeirAdapter(mini_beir).validate(["test"])


def test_archive_validation_rejects_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")

    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(ValueError, match="unsafe archive member"):
            _validated_members(archive)


def test_ragbench_adapter_reads_all_fixed_subsets_and_splits(tmp_path: Path) -> None:
    root = tmp_path / "ragbench"
    for subset in RAGBENCH_SUBSETS:
        subset_root = root / subset
        subset_root.mkdir(parents=True)
        for split in RAGBENCH_SPLITS:
            row = {
                "id": f"{subset}-{split}-1",
                "question": "Which fact is supported?",
                "documents": ["The supported fact is alpha.", "Irrelevant beta."],
                "response": "The supported fact is alpha.",
                "generation_model_name": "example-generator",
                "annotating_model_name": "example-annotator",
                "dataset_name": f"{subset}_{split}",
                "unsupported_response_sentence_keys": [],
                "adherence_score": True,
                "all_relevant_sentence_keys": ["d0s0"],
                "all_utilized_sentence_keys": ["d0s0"],
                "relevance_score": 0.5,
                "utilization_score": 1.0,
                "completeness_score": 1.0,
                "trulens_groundedness": 0.9,
                "trulens_context_relevance": 0.8,
                "ragas_faithfulness": 0.85,
                "ragas_context_relevance": 0.75,
                "gpt3_adherence": 1.0,
                "gpt3_context_relevance": 0.9,
                "gpt35_utilization": 0.7,
            }
            pq.write_table(
                pa.Table.from_pylist([row]),
                subset_root / f"{split}-00000-of-00001.parquet",
            )

    adapter = RagBenchAdapter(root)
    example = next(adapter.iter_examples(split="test", subset="covidqa"))
    counts = adapter.validate()

    assert example.example_id == "covidqa-test-1"
    assert example.documents == (
        "The supported fact is alpha.",
        "Irrelevant beta.",
    )
    assert example.adherence_score is True
    assert example.published_scores["ragas_faithfulness"] == 0.85
    assert counts["all"] == {
        "responses": 36,
        "labeled_responses": 36,
        "adherent_responses": 36,
    }
    assert counts["test"] == {
        "responses": 12,
        "labeled_responses": 12,
        "adherent_responses": 12,
    }
    assert counts["covidqa/test"] == {
        "responses": 1,
        "labeled_responses": 1,
        "adherent_responses": 1,
    }


def test_ragbench_adapter_rejects_negative_scores(tmp_path: Path) -> None:
    root = tmp_path / "ragbench" / "covidqa"
    root.mkdir(parents=True)
    row = {
        "id": "bad-score",
        "question": "Question?",
        "documents": ["Context."],
        "response": "Answer.",
        "generation_model_name": "generator",
        "annotating_model_name": "annotator",
        "dataset_name": "covidqa",
        "unsupported_response_sentence_keys": [],
        "adherence_score": False,
        "all_relevant_sentence_keys": [],
        "all_utilized_sentence_keys": [],
        "relevance_score": -0.1,
        "utilization_score": 0.0,
        "completeness_score": 0.0,
        "trulens_groundedness": None,
        "trulens_context_relevance": None,
        "ragas_faithfulness": None,
        "ragas_context_relevance": None,
        "gpt3_adherence": None,
        "gpt3_context_relevance": None,
        "gpt35_utilization": None,
    }
    pq.write_table(
        pa.Table.from_pylist([row]),
        root / "test-00000-of-00001.parquet",
    )

    with pytest.raises(ValueError, match="non-negative"):
        next(RagBenchAdapter(root.parent).iter_examples(split="test", subset="covidqa"))
