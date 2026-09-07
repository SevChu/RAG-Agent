from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    BeirAdapter,
    RelevanceJudgment,
    document_text,
    evaluate_retrieval,
    hash_file,
    write_json_atomic,
)
from scripts.run_retrieval_benchmark import (  # noqa: E402
    DEFAULT_DATASET_ROOT,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANKER_MODEL,
    METRIC_KS,
    RRF_CONSTANT,
    RUN_TOP_K,
    ensure_corpus_embeddings,
    execute_or_load,
    load_or_create_state,
    model_identity,
    paired_bootstrap_delta,
    run_bm25,
    run_dense,
    run_hybrid,
    run_reranker,
    verify_frozen_dataset,
)

FINAL_RUN_ID = "w6-extra-d2-fiqa-final-test"
PARENT_DECISION_SHA256 = "d3ae9dc0369b91d7278a08ec966a8a9829de66c1324092223ed04041b7b76fb4"
FIQA_MANIFEST_SHA256 = "7d6cf6534f4176a7288279f34dacc4aea43eec074f846dde6ec5262e1b154092"
APPROVAL_PROTOCOL_SHA256 = "ddc14d377a3968ecf0865188644c44ff6997b98fd42a95c9b1467c5cec04a00c"
EXPECTED_TEST_QUERIES = 648
EXPECTED_TEST_QRELS = 1706
DEFAULT_PARENT_DECISION = _BACKEND_ROOT / "datasets/benchmarks/week06-extra/decision.json"
DEFAULT_OUTPUT = DEFAULT_DATASET_ROOT / "runs/week06-extra-day02/final-test"
APPROVAL_DOC = _REPO_ROOT / "docs/deliverables/week-06-extra-confirmation-protocol.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the approved one-shot frozen FiQA dense-rerank final test"
    )
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--parent-decision", type=Path, default=DEFAULT_PARENT_DECISION)
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--reranker-model", type=Path, default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    return parser


def verify_approval() -> str:
    if hash_file(APPROVAL_DOC) != APPROVAL_PROTOCOL_SHA256:
        raise ValueError("final-test approval protocol hash changed")
    text = APPROVAL_DOC.read_text(encoding="utf-8")
    required = (
        "用户于 2026-09-07 批准一次性运行 Day 2 FiQA 官方 test",
        "只有全部门通过才可标记 `accept_advisory_profile`",
        "不调参、不拟合、不重训、不因结果",
    )
    if any(item not in text for item in required):
        raise ValueError("Day 2 final-test approval record is incomplete")
    return APPROVAL_PROTOCOL_SHA256


def load_parent_decision(path: Path) -> dict[str, Any]:
    if hash_file(path) != PARENT_DECISION_SHA256:
        raise ValueError("parent Extra decision differs from the approved frozen identity")
    payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    day2 = payload.get("day2", {})
    if (
        payload.get("test_access") != "forbidden_and_not_read"
        or day2.get("outcome") != "minimum_test_eligible"
        or day2.get("official_test_run") is not False
        or not day2.get("gates", {}).get("all_passed")
    ):
        raise ValueError("parent Extra decision did not authorize a final test")
    return payload


def _group_qrels(
    qrels: tuple[RelevanceJudgment, ...],
) -> dict[str, tuple[RelevanceJudgment, ...]]:
    grouped: dict[str, list[RelevanceJudgment]] = {}
    for judgment in qrels:
        grouped.setdefault(judgment.query_id, []).append(judgment)
    return {query_id: tuple(values) for query_id, values in grouped.items()}


def final_decision(
    *,
    paired: dict[str, Any],
    recall_delta_from_dense: float,
    latency_delta_ms: float,
) -> dict[str, Any]:
    gates = {
        "mean_ndcg_delta_positive": float(paired["mean_delta"]) > 0.0,
        "paired_bootstrap_ci_lower_positive": float(paired["ci95"]["lower"]) > 0.0,
        "recall_at_100_not_below_dense": recall_delta_from_dense >= 0.0,
        "latency_regression_within_750ms": latency_delta_ms <= 750.0,
    }
    return {
        "gates": {**gates, "all_passed": all(gates.values())},
        "outcome": "accept_advisory_profile" if all(gates.values()) else "reject",
    }


def main() -> int:
    arguments = build_parser().parse_args()
    output = arguments.output.resolve()
    summary_path = output / "summary.json"
    if summary_path.exists():
        existing = cast(dict[str, Any], json.loads(summary_path.read_text(encoding="utf-8")))
        if existing.get("status") == "complete":
            raise FileExistsError("refusing to repeat a completed FiQA final test")

    approval_hash = verify_approval()
    parent_path = arguments.parent_decision.resolve()
    load_parent_decision(parent_path)
    dataset_root = arguments.dataset_root.resolve()
    manifest_path = dataset_root / "manifest.json"
    if hash_file(manifest_path) != FIQA_MANIFEST_SHA256:
        raise ValueError("FiQA manifest differs from the frozen final-test identity")

    started = time.perf_counter()
    manifest = verify_frozen_dataset(dataset_root, allowed_splits={"test"})
    adapter = BeirAdapter(dataset_root / "raw")
    documents = list(adapter.iter_corpus())
    queries = adapter.queries("test")
    qrels = adapter.qrels("test")
    if len(queries) != EXPECTED_TEST_QUERIES or len(qrels) != EXPECTED_TEST_QRELS:
        raise ValueError("FiQA official test counts differ from the frozen manifest")
    query_texts = {query.id: query.text for query in queries}
    document_texts = {document.id: document_text(document) for document in documents}
    embedding_model = arguments.embedding_model.resolve()
    reranker_model = arguments.reranker_model.resolve()
    output.mkdir(parents=True, exist_ok=True)

    identity = {
        "schema_version": "1.0",
        "run_id": FINAL_RUN_ID,
        "parent_decision_sha256": PARENT_DECISION_SHA256,
        "approval_protocol_sha256": approval_hash,
        "dataset_manifest_sha256": FIQA_MANIFEST_SHA256,
        "dataset_archive_sha256": manifest.archive_sha256,
        "corpus_sha256": manifest.files["corpus.jsonl"],
        "queries_sha256": manifest.files["queries.jsonl"],
        "test_qrels_sha256": manifest.files["qrels/test.tsv"],
        "split": "test",
        "query_count": len(queries),
        "qrels_count": len(qrels),
        "corpus_count": len(documents),
        "metric_ks": list(METRIC_KS),
        "run_top_k": RUN_TOP_K,
        "bm25": {"k1": 1.2, "b": 0.75, "tokenizer": "agentic-en-v1"},
        "dense": {
            "model": model_identity(embedding_model),
            "batch_size": 8,
            "normalized": True,
            "search": "exact-cosine",
        },
        "hybrid": {"method": "rrf", "rank_constant": RRF_CONSTANT},
        "reranker": {
            "model": model_identity(reranker_model),
            "batch_size": 4,
            "max_length": 512,
            "candidate_k": RUN_TOP_K,
        },
        "seed": 42,
        "model_fits": 0,
        "threshold_calibrations": 0,
        "official_test_accesses": 1,
    }
    state = load_or_create_state(output, identity=identity)
    runs: dict[str, Any] = {}
    runs["bm25"] = execute_or_load(
        "bm25", output, qrels, lambda: run_bm25(documents, query_texts), state
    )
    embeddings, document_ids, cache_details = ensure_corpus_embeddings(
        documents,
        dataset_root,
        embedding_model,
        arguments.device,
        8,
        manifest.files["corpus.jsonl"],
    )
    if (
        cache_details.get("identity", {}).get("corpus_sha256")
        != manifest.files["corpus.jsonl"]
    ):
        raise ValueError("frozen corpus embedding cache identity changed")
    runs["dense"] = execute_or_load(
        "dense",
        output,
        qrels,
        lambda: run_dense(
            embeddings, document_ids, query_texts, embedding_model, arguments.device, 8
        ),
        state,
    )
    runs["hybrid"] = execute_or_load(
        "hybrid",
        output,
        qrels,
        lambda: run_hybrid(runs["bm25"], runs["dense"]),
        state,
    )
    runs["rerank"] = execute_or_load(
        "rerank",
        output,
        qrels,
        lambda: run_reranker(
            runs["hybrid"], query_texts, document_texts, reranker_model, arguments.device, 4
        ),
        state,
    )
    runs["dense-rerank"] = execute_or_load(
        "dense-rerank",
        output,
        qrels,
        lambda: run_reranker(
            runs["dense"], query_texts, document_texts, reranker_model, arguments.device, 4
        ),
        state,
    )

    grouped = _group_qrels(qrels)
    query_ids = tuple(query_texts)
    baseline_query_ndcg = [
        evaluate_retrieval(
            {query_id: runs["rerank"][query_id]}, grouped[query_id], ks=(10,)
        ).values["ndcg@10"]
        for query_id in query_ids
    ]
    candidate_query_ndcg = [
        evaluate_retrieval(
            {query_id: runs["dense-rerank"][query_id]}, grouped[query_id], ks=(10,)
        ).values["ndcg@10"]
        for query_id in query_ids
    ]
    paired = paired_bootstrap_delta(
        baseline_query_ndcg, candidate_query_ndcg, seed=42, resamples=10_000
    )
    experiments = state["experiments"]
    metric_deltas = {
        metric: experiments["dense-rerank"]["metrics"][metric]
        - experiments["rerank"]["metrics"][metric]
        for metric in ("ndcg@10", "recall@100", "mrr@10", "map@100")
    }
    recall_delta_from_dense = (
        experiments["dense-rerank"]["metrics"]["recall@100"]
        - experiments["dense"]["metrics"]["recall@100"]
    )
    latency_delta_ms = (
        experiments["dense-rerank"]["latency"]["mean_ms"]
        - experiments["rerank"]["latency"]["mean_ms"]
    )
    decision = final_decision(
        paired=paired,
        recall_delta_from_dense=recall_delta_from_dense,
        latency_delta_ms=latency_delta_ms,
    )
    public_methods = {
        name: {
            "metrics": payload["metrics"],
            "query_count": payload["query_count"],
            "run_sha256": payload["run_sha256"],
            "wall_seconds": payload["wall_seconds"],
            "latency": payload["latency"],
        }
        for name, payload in experiments.items()
    }
    final_summary = {
        "schema_version": "1.0",
        "status": "complete",
        "run_id": FINAL_RUN_ID,
        "benchmark": "beir-fiqa-2018",
        "decision_split": "test",
        "decision": decision["outcome"],
        "identity": identity,
        "methods": public_methods,
        "comparison": {
            "baseline": "rerank",
            "candidate": "dense-rerank",
            "metric_deltas": metric_deltas,
            "recall_at_100_delta_from_dense": recall_delta_from_dense,
            "mean_latency_delta_ms": latency_delta_ms,
            "paired_query_ndcg_at_10": paired,
        },
        "gates": decision["gates"],
        "runtime": {
            "wall_seconds": time.perf_counter() - started,
            "new_model_downloads": 0,
            "external_api_calls": 0,
            "model_fits": 0,
            "threshold_calibrations": 0,
        },
        "privacy": {
            "published_summary_contains_query_or_document_ids": False,
            "published_summary_contains_text": False,
            "local_run_files_are_git_ignored": True,
        },
        "runner_sha256": hash_file(Path(__file__)),
    }
    write_json_atomic(summary_path, final_summary)
    print(
        json.dumps(
            {
                "comparison": final_summary["comparison"],
                "gates": final_summary["gates"],
                "decision": final_summary["decision"],
                "summary": str(summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    raise SystemExit(main())
