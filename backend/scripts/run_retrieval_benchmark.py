from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psutil  # type: ignore[import-untyped]
import torch
from numpy.lib.format import open_memmap
from numpy.typing import NDArray

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    BeirAdapter,
    BenchmarkManifest,
    Bm25Index,
    RetrievalHit,
    document_text,
    evaluate_retrieval,
    hash_file,
    read_trec_run,
    reciprocal_rank_fusion,
    write_json_atomic,
    write_trec_run,
)
from app.knowledge import BgeM3Embedder  # noqa: E402
from app.retrieval import BgeReranker  # noqa: E402

DEFAULT_DATASET_ROOT = BACKEND_ROOT / "datasets" / "benchmarks" / "beir-fiqa-2018"
DEFAULT_OUTPUT_ROOT = DEFAULT_DATASET_ROOT / "runs" / "week05-day03"
DEFAULT_EMBEDDING_MODEL = PROJECT_ROOT / "data" / "models" / "embedding" / "bge-m3"
DEFAULT_RERANKER_MODEL = PROJECT_ROOT / "data" / "models" / "reranker" / "bge-reranker-v2-m3"
METRIC_KS = (1, 3, 5, 10, 20, 100)
RUN_TOP_K = 100
RRF_CONSTANT = 60


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run reproducible FiQA retrieval baselines without generation APIs."
    )
    parser.add_argument(
        "--methods",
        default="bm25,dense,hybrid,rerank",
        help="Comma-separated subset of bm25,dense,hybrid,rerank.",
    )
    parser.add_argument(
        "--force-methods",
        default="",
        help="Comma-separated completed methods to rerun for profiling.",
    )
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--split", default="test", choices=("train", "dev", "test"))
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--reranker-model", type=Path, default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--embedding-batch-size", type=int, default=8)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    methods = tuple(dict.fromkeys(part.strip() for part in args.methods.split(",") if part.strip()))
    forced = {part.strip() for part in args.force_methods.split(",") if part.strip()}
    unknown = set(methods).difference({"bm25", "dense", "hybrid", "rerank"})
    unknown.update(forced.difference({"bm25", "dense", "hybrid", "rerank"}))
    if not forced.issubset(methods):
        raise ValueError("forced methods must also be included in --methods")
    if unknown:
        raise ValueError(f"unknown methods: {', '.join(sorted(unknown))}")
    if "rerank" in methods:
        methods = tuple(dict.fromkeys((*methods, "bm25", "dense", "hybrid")))
    elif "hybrid" in methods:
        methods = tuple(dict.fromkeys((*methods, "bm25", "dense")))
    if args.embedding_batch_size < 1 or args.reranker_batch_size < 1:
        raise ValueError("model batch sizes must be positive")

    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    raw_root = dataset_root / "raw"
    manifest = verify_frozen_dataset(dataset_root)
    adapter = BeirAdapter(raw_root)
    documents = list(adapter.iter_corpus())
    queries = adapter.queries(args.split)
    qrels = adapter.qrels(args.split)
    query_texts = {query.id: query.text for query in queries}
    document_texts = {document.id: document_text(document) for document in documents}
    output_root.mkdir(parents=True, exist_ok=True)

    state = load_or_create_state(
        output_root,
        identity={
            "schema_version": "1.0",
            "dataset_id": manifest.dataset_id,
            "dataset_archive_sha256": manifest.archive_sha256,
            "corpus_sha256": manifest.files["corpus.jsonl"],
            "split": args.split,
            "query_count": len(queries),
            "qrels_count": len(qrels),
            "corpus_count": len(documents),
            "metric_ks": list(METRIC_KS),
            "run_top_k": RUN_TOP_K,
            "bm25": {"k1": 1.2, "b": 0.75, "tokenizer": "agentic-en-v1"},
            "dense": {
                "model": model_identity(args.embedding_model.resolve()),
                "batch_size": args.embedding_batch_size,
                "normalized": True,
                "search": "exact-cosine",
            },
            "hybrid": {"method": "rrf", "rank_constant": RRF_CONSTANT},
            "reranker": {
                "model": model_identity(args.reranker_model.resolve()),
                "batch_size": args.reranker_batch_size,
                "max_length": 512,
                "candidate_source": "hybrid-rrf",
                "candidate_k": RUN_TOP_K,
            },
            "seed": 42,
            "test_split_tuning": False,
            "hardware": hardware_info(),
        },
    )

    runs: dict[str, dict[str, tuple[RetrievalHit, ...]]] = {}
    if "bm25" in methods:
        runs["bm25"] = execute_or_load(
            "bm25",
            output_root,
            qrels,
            lambda: run_bm25(documents, query_texts),
            state,
            force="bm25" in forced,
        )

    if "dense" in methods:
        embeddings, document_ids, cache_details = ensure_corpus_embeddings(
            documents,
            dataset_root,
            args.embedding_model.resolve(),
            args.device,
            args.embedding_batch_size,
            manifest.files["corpus.jsonl"],
        )
        state["embedding_cache"] = cache_details
        write_json_atomic(output_root / "summary.json", state)
        runs["dense"] = execute_or_load(
            "dense",
            output_root,
            qrels,
            lambda: run_dense(
                embeddings,
                document_ids,
                query_texts,
                args.embedding_model.resolve(),
                args.device,
                args.embedding_batch_size,
            ),
            state,
            force="dense" in forced,
        )
        del embeddings
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    if "hybrid" in methods:
        runs["hybrid"] = execute_or_load(
            "hybrid",
            output_root,
            qrels,
            lambda: run_hybrid(runs["bm25"], runs["dense"]),
            state,
            force="hybrid" in forced,
        )

    if "rerank" in methods:
        runs["rerank"] = execute_or_load(
            "rerank",
            output_root,
            qrels,
            lambda: run_reranker(
                runs["hybrid"],
                query_texts,
                document_texts,
                args.reranker_model.resolve(),
                args.device,
                args.reranker_batch_size,
            ),
            state,
            force="rerank" in forced,
        )

    state["status"] = (
        "complete" if all(name in state["experiments"] for name in methods) else "partial"
    )
    state["updated_at"] = datetime.now(UTC).isoformat()
    write_json_atomic(output_root / "summary.json", state)
    print(json.dumps(compact_results(state), ensure_ascii=False, indent=2), flush=True)
    return 0


def verify_frozen_dataset(dataset_root: Path) -> BenchmarkManifest:
    manifest_path = dataset_root / "manifest.json"
    manifest = BenchmarkManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    raw_root = dataset_root / "raw"
    for relative_path, expected_sha256 in manifest.files.items():
        actual = hash_file(raw_root / relative_path)
        if actual != expected_sha256:
            raise ValueError(f"frozen dataset hash mismatch: {relative_path}")
    return manifest


def load_or_create_state(output_root: Path, *, identity: dict[str, Any]) -> dict[str, Any]:
    summary_path = output_root / "summary.json"
    if summary_path.exists():
        stored = json.loads(summary_path.read_text(encoding="utf-8"))
        if stored.get("identity") != identity:
            raise ValueError("existing output belongs to a different benchmark configuration")
        return dict(stored)
    state = {
        "schema_version": "1.0",
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
        "identity": identity,
        "experiments": {},
    }
    write_json_atomic(summary_path, state)
    return state


def execute_or_load(
    name: str,
    output_root: Path,
    qrels: Sequence[Any],
    operation: Callable[[], tuple[dict[str, tuple[RetrievalHit, ...]], dict[str, Any]]],
    state: dict[str, Any],
    force: bool = False,
) -> dict[str, tuple[RetrievalHit, ...]]:
    run_path = output_root / f"{name}.run"
    if force:
        state["experiments"].pop(name, None)
    if name in state["experiments"] and run_path.exists():
        print(f"[{name}] loading completed run", flush=True)
        return read_trec_run(run_path)
    print(f"[{name}] starting", flush=True)
    process = psutil.Process()
    memory_before = process.memory_info()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    run, details = operation()
    elapsed = time.perf_counter() - started
    memory_after = process.memory_info()
    resources = {
        "rss_before_bytes": memory_before.rss,
        "rss_after_bytes": memory_after.rss,
        "peak_working_set_bytes": getattr(memory_after, "peak_wset", memory_after.rss),
        "gpu_peak_allocated_bytes": (
            torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0
        ),
        "gpu_peak_reserved_bytes": (
            torch.cuda.max_memory_reserved() if torch.cuda.is_available() else 0
        ),
    }
    metrics = evaluate_retrieval(run, qrels, ks=METRIC_KS)
    write_trec_run(run_path, run, run_name=f"agentic-fiqa-{name}")
    state["experiments"][name] = {
        "metrics": metrics.values,
        "query_count": metrics.query_count,
        "run_sha256": hash_file(run_path),
        "run_file": run_path.name,
        "wall_seconds": elapsed,
        "resources": resources,
        **details,
    }
    state["updated_at"] = datetime.now(UTC).isoformat()
    write_json_atomic(output_root / "summary.json", state)
    print(
        f"[{name}] complete in {elapsed:.2f}s; "
        f"nDCG@10={metrics.values['ndcg@10']:.4f}; "
        f"Recall@100={metrics.values['recall@100']:.4f}",
        flush=True,
    )
    return run


def run_bm25(
    documents: Sequence[Any],
    queries: Mapping[str, str],
) -> tuple[dict[str, tuple[RetrievalHit, ...]], dict[str, Any]]:
    index_started = time.perf_counter()
    index = Bm25Index(documents, k1=1.2, b=0.75)
    index_seconds = time.perf_counter() - index_started
    latencies: list[float] = []
    run: dict[str, tuple[RetrievalHit, ...]] = {}
    for position, (query_id, query) in enumerate(queries.items(), start=1):
        started = time.perf_counter()
        run[query_id] = index.search(query, top_k=RUN_TOP_K)
        latencies.append(time.perf_counter() - started)
        report_progress("bm25", position, len(queries), every=100)
    return run, {"index_seconds": index_seconds, "latency": latency_summary(latencies)}


def ensure_corpus_embeddings(
    documents: Sequence[Any],
    dataset_root: Path,
    model_path: Path,
    device: str,
    batch_size: int,
    corpus_sha256: str,
) -> tuple[NDArray[np.float32], list[str], dict[str, Any]]:
    cache_root = dataset_root / "cache" / "bge-m3-dense"
    matrix_path = cache_root / "corpus.npy"
    metadata_path = cache_root / "metadata.json"
    ids_path = cache_root / "document-ids.json"
    expected = {
        "corpus_sha256": corpus_sha256,
        "model": model_identity(model_path),
        "rows": len(documents),
        "dimension": 1024,
        "normalized": True,
    }
    if metadata_path.exists() and matrix_path.exists() and ids_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("identity") == expected:
            print("[dense-cache] reusing frozen corpus embeddings", flush=True)
            ids = list(json.loads(ids_path.read_text(encoding="utf-8")))
            return np.load(matrix_path, mmap_mode="r+"), ids, metadata

    cache_root.mkdir(parents=True, exist_ok=True)
    temporary_path = matrix_path.with_suffix(".npy.tmp")
    embedder = BgeM3Embedder(model_path, device=device, batch_size=batch_size)
    matrix = open_memmap(  # type: ignore[no-untyped-call]
        temporary_path,
        mode="w+",
        dtype=np.float32,
        shape=(len(documents), embedder.dimension),
    )
    started = time.perf_counter()
    empty_count = 0
    for offset in range(0, len(documents), batch_size):
        batch = documents[offset : offset + batch_size]
        texts = [document_text(document) for document in batch]
        nonempty = [index for index, text in enumerate(texts) if text]
        matrix[offset : offset + len(batch)] = 0.0
        if nonempty:
            vectors = embedder.embed([texts[index] for index in nonempty])
            for source_index, vector in zip(nonempty, vectors.vectors, strict=True):
                matrix[offset + source_index] = np.asarray(vector, dtype=np.float32)
        empty_count += len(batch) - len(nonempty)
        report_progress(
            "dense-cache", min(offset + len(batch), len(documents)), len(documents), every=512
        )
    matrix.flush()
    del matrix
    temporary_path.replace(matrix_path)
    ids = [document.id for document in documents]
    write_json_atomic(ids_path, ids)
    metadata = {
        "identity": expected,
        "created_at": datetime.now(UTC).isoformat(),
        "embedding_seconds": time.perf_counter() - started,
        "device": embedder.active_device,
        "empty_document_vectors": empty_count,
        "matrix_bytes": matrix_path.stat().st_size,
    }
    write_json_atomic(metadata_path, metadata)
    return np.load(matrix_path, mmap_mode="r+"), ids, metadata


def run_dense(
    corpus_embeddings: NDArray[np.float32],
    document_ids: Sequence[str],
    queries: Mapping[str, str],
    model_path: Path,
    device: str,
    batch_size: int,
) -> tuple[dict[str, tuple[RetrievalHit, ...]], dict[str, Any]]:
    embedder = BgeM3Embedder(model_path, device=device, batch_size=batch_size)
    query_ids = list(queries)
    query_vectors: list[NDArray[np.float32]] = []
    embedding_started = time.perf_counter()
    for offset in range(0, len(query_ids), batch_size):
        texts = [queries[query_id] for query_id in query_ids[offset : offset + batch_size]]
        batch = embedder.embed(texts)
        query_vectors.extend(np.asarray(vector, dtype=np.float32) for vector in batch.vectors)
    query_embedding_seconds = time.perf_counter() - embedding_started
    search_started = time.perf_counter()
    run, latencies, search_device = exact_dense_search(
        corpus_embeddings,
        document_ids,
        query_ids,
        np.stack(query_vectors),
        device=embedder.active_device,
    )
    return run, {
        "query_embedding_seconds": query_embedding_seconds,
        "search_seconds": time.perf_counter() - search_started,
        "latency": latency_summary(latencies),
        "embedding_device": embedder.active_device,
        "search_device": search_device,
    }


def exact_dense_search(
    corpus_embeddings: NDArray[np.float32],
    document_ids: Sequence[str],
    query_ids: Sequence[str],
    query_embeddings: NDArray[np.float32],
    *,
    device: str,
) -> tuple[dict[str, tuple[RetrievalHit, ...]], list[float], str]:
    use_cuda = device == "cuda" and torch.cuda.is_available()
    torch_device = "cuda" if use_cuda else "cpu"
    corpus = torch.from_numpy(np.asarray(corpus_embeddings)).to(torch_device)
    queries = torch.from_numpy(query_embeddings).to(torch_device)
    run: dict[str, tuple[RetrievalHit, ...]] = {}
    latencies: list[float] = []
    for position, query_id in enumerate(query_ids, start=1):
        if use_cuda:
            torch.cuda.synchronize()
        started = time.perf_counter()
        scores = torch.mv(corpus, queries[position - 1])
        values, indices = torch.topk(scores, k=min(RUN_TOP_K, len(document_ids)))
        if use_cuda:
            torch.cuda.synchronize()
        latencies.append(time.perf_counter() - started)
        ranked = sorted(
            (
                RetrievalHit(document_ids[index], float(score))
                for score, index in zip(values.cpu().tolist(), indices.cpu().tolist(), strict=True)
            ),
            key=lambda hit: (hit.score, hit.document_id),
            reverse=True,
        )
        run[query_id] = tuple(ranked)
        report_progress("dense", position, len(query_ids), every=100)
    del corpus, queries
    return run, latencies, torch_device


def run_hybrid(
    bm25_run: Mapping[str, Sequence[RetrievalHit]],
    dense_run: Mapping[str, Sequence[RetrievalHit]],
) -> tuple[dict[str, tuple[RetrievalHit, ...]], dict[str, Any]]:
    started = time.perf_counter()
    run: dict[str, tuple[RetrievalHit, ...]] = {}
    latencies: list[float] = []
    for query_id in sorted(set(bm25_run) | set(dense_run)):
        query_started = time.perf_counter()
        run[query_id] = reciprocal_rank_fusion(
            [bm25_run.get(query_id, ()), dense_run.get(query_id, ())],
            top_k=RUN_TOP_K,
            rank_constant=RRF_CONSTANT,
        )
        latencies.append(time.perf_counter() - query_started)
    elapsed = time.perf_counter() - started
    return run, {
        "fusion_seconds": elapsed,
        "latency": latency_summary(latencies),
    }


def run_reranker(
    candidates: Mapping[str, Sequence[RetrievalHit]],
    queries: Mapping[str, str],
    document_texts: Mapping[str, str],
    model_path: Path,
    device: str,
    batch_size: int,
) -> tuple[dict[str, tuple[RetrievalHit, ...]], dict[str, Any]]:
    reranker = BgeReranker(
        model_path,
        device=device,
        batch_size=batch_size,
        max_length=512,
    )
    run: dict[str, tuple[RetrievalHit, ...]] = {}
    latencies: list[float] = []
    for position, query_id in enumerate(queries, start=1):
        hits = candidates.get(query_id, ())
        passages = [document_texts[hit.document_id] for hit in hits]
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        started = time.perf_counter()
        scores = reranker.score_passages(queries[query_id], passages)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        latencies.append(time.perf_counter() - started)
        ranked = sorted(
            (RetrievalHit(hit.document_id, score) for hit, score in zip(hits, scores, strict=True)),
            key=lambda hit: (hit.score, hit.document_id),
            reverse=True,
        )
        run[query_id] = tuple(ranked[:RUN_TOP_K])
        report_progress("rerank", position, len(queries), every=25)
    return run, {
        "latency": latency_summary(latencies),
        "reranker_device": reranker.active_device,
        "candidate_k": RUN_TOP_K,
    }


def model_identity(model_path: Path) -> dict[str, Any]:
    if not model_path.is_dir():
        raise FileNotFoundError(f"local model directory does not exist: {model_path}")
    tree_files = sorted((model_path / ".cache" / "huggingface" / "trees").glob("*.json"))
    weight_sha256 = None
    revision = None
    if tree_files:
        revision = tree_files[0].stem
        tree = json.loads(tree_files[0].read_text(encoding="utf-8"))
        weight_sha256 = tree.get("files", {}).get("model.safetensors", {}).get("lfs_sha256")
    config_path = model_path / "config.json"
    return {
        "path": str(model_path),
        "revision": revision,
        "weight_sha256": weight_sha256,
        "config_sha256": hash_file(config_path),
    }


def hardware_info() -> dict[str, Any]:
    gpu = None
    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        gpu = {
            "name": properties.name,
            "total_memory_bytes": properties.total_memory,
            "cuda_runtime": torch.version.cuda,
        }
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "torch": torch.__version__,
        "gpu": gpu,
    }


def latency_summary(values: Sequence[float]) -> dict[str, float]:
    milliseconds = [value * 1000.0 for value in values]
    ordered = sorted(milliseconds)
    return {
        "mean_ms": statistics.fmean(milliseconds) if milliseconds else 0.0,
        "p50_ms": percentile(ordered, 0.50),
        "p95_ms": percentile(ordered, 0.95),
        "max_ms": max(milliseconds, default=0.0),
        "queries_per_second": len(values) / sum(values) if sum(values) else 0.0,
    }


def percentile(ordered: Sequence[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def report_progress(label: str, completed: int, total: int, *, every: int) -> None:
    if completed == total or completed % every == 0:
        print(f"[{label}] {completed}/{total}", flush=True)


def compact_results(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: {
            "ndcg@10": payload["metrics"]["ndcg@10"],
            "recall@100": payload["metrics"]["recall@100"],
            "mrr@10": payload["metrics"]["mrr@10"],
            "map@100": payload["metrics"]["map@100"],
            "wall_seconds": payload["wall_seconds"],
        }
        for name, payload in state["experiments"].items()
    }


if __name__ == "__main__":
    raise SystemExit(main())
