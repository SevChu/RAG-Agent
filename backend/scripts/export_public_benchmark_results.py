from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARK_ROOT = _REPO_ROOT / "backend" / "datasets" / "benchmarks"
DEFAULT_FIQA_SUMMARY = _BENCHMARK_ROOT / "beir-fiqa-2018" / "runs" / "week05-day03" / "summary.json"
DEFAULT_RAGTRUTH_SUMMARY = (
    _BENCHMARK_ROOT / "ragtruth" / "runs" / "week05-day04-ragtruth" / "summary.json"
)
DEFAULT_RAGBENCH_SUMMARY = (
    _BENCHMARK_ROOT / "ragbench" / "runs" / "week05-day04-ragbench" / "summary.json"
)
DEFAULT_RAGBENCH_FIRST_SUMMARY = (
    _BENCHMARK_ROOT / "ragbench" / "runs" / "week05-day04-ragbench" / "summary-first-run.json"
)
DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "benchmarks" / "v1.1.0"

_FORBIDDEN_KEYS = {
    "answer",
    "api_key",
    "context",
    "documents",
    "local_path",
    "path",
    "prompt",
    "query",
    "row_id",
    "source_id",
    "text",
}
_FORBIDDEN_TEXT = ("d:\\", "c:\\", "/users/", "test-predictions.jsonl")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"expected an object for {label}")
    return value


def _public_model(model: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": "BAAI/bge-m3",
        "revision": model["revision"],
        "weight_sha256": model["weight_sha256"],
        "config_sha256": model["config_sha256"],
    }


def _public_hardware(runtime: Mapping[str, Any]) -> dict[str, Any]:
    hardware = _mapping(runtime["hardware"], "runtime.hardware")
    gpu = _mapping(hardware["gpu"], "runtime.hardware.gpu")
    result: dict[str, Any] = {
        "os_family": "Windows x64",
        "python": hardware["python"],
        "logical_cpu_count": hardware["logical_cpu_count"],
        "torch": hardware["torch"],
        "gpu": {
            "name": gpu["name"],
            "total_memory_bytes": gpu["total_memory_bytes"],
            "cuda_runtime": gpu["cuda_runtime"],
        },
    }
    if "sklearn" in hardware:
        result["sklearn"] = hardware["sklearn"]
    return result


def _public_ragtruth_methods(methods: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in methods.items():
        method = _mapping(value, f"ragtruth.methods.{name}")
        result[name] = {
            "thresholds": method["thresholds"],
            "response_level": method["response"],
            "response_by_task": method["response_by_task"],
            "span_char": method["span_char"],
        }
    return result


def build_public_results(
    *,
    fiqa: Mapping[str, Any],
    ragtruth: Mapping[str, Any],
    ragbench: Mapping[str, Any],
    ragbench_first: Mapping[str, Any],
) -> dict[str, Any]:
    fiqa_identity = _mapping(fiqa["identity"], "fiqa.identity")
    fiqa_dense = _mapping(fiqa_identity["dense"], "fiqa.identity.dense")
    fiqa_reranker = _mapping(fiqa_identity["reranker"], "fiqa.identity.reranker")
    fiqa_experiments = _mapping(fiqa["experiments"], "fiqa.experiments")
    fiqa_public_methods: dict[str, Any] = {}
    for name in ("bm25", "dense", "hybrid", "rerank"):
        experiment = _mapping(fiqa_experiments[name], f"fiqa.experiments.{name}")
        public_experiment = {
            "metrics": experiment["metrics"],
            "wall_seconds": experiment["wall_seconds"],
            "resources": experiment["resources"],
            "latency": experiment["latency"],
            "run_sha256": experiment["run_sha256"],
        }
        fiqa_public_methods[name] = public_experiment

    truth_protocol = _mapping(ragtruth["protocol"], "ragtruth.protocol")
    truth_dense = _mapping(ragtruth["dense"], "ragtruth.dense")
    truth_runtime = _mapping(ragtruth["runtime"], "ragtruth.runtime")
    truth_artifacts = _mapping(ragtruth["artifacts"], "ragtruth.artifacts")

    bench_protocol = _mapping(ragbench["protocol"], "ragbench.protocol")
    bench_dense = _mapping(ragbench["dense"], "ragbench.dense")
    bench_runtime = _mapping(ragbench["runtime"], "ragbench.runtime")
    bench_first_runtime = _mapping(ragbench_first["runtime"], "ragbench_first.runtime")
    bench_artifacts = _mapping(ragbench["artifacts"], "ragbench.artifacts")

    payload = {
        "schema_version": "1.0",
        "release_version": "1.1.0",
        "generated_on": "2026-08-30",
        "publication_policy": {
            "aggregation_only": True,
            "contains_sample_text": False,
            "contains_row_level_predictions": False,
            "contains_local_paths": False,
            "contains_personal_or_workspace_data": False,
            "raw_datasets_redistributed": False,
            "artifact_hashes_are_identifiers_only": True,
        },
        "test_policy": (
            "test splits are final-report-only; optimization uses train and validation only"
        ),
        "hardware_class": _public_hardware(bench_runtime),
        "datasets": {
            "beir-fiqa-2018": {
                "display_name": "BEIR FiQA-2018",
                "task": "retrieval",
                "source": "https://github.com/beir-cellar/beir/wiki/Datasets-available",
                "license": "FiQA research-use terms; training and test data are non-commercial use",
                "citation": "Maia et al. (2018); Thakur et al. (2021)",
                "dataset_revision": f"archive-sha256:{fiqa_identity['dataset_archive_sha256']}",
                "split": fiqa_identity["split"],
                "counts": {
                    "corpus": fiqa_identity["corpus_count"],
                    "queries": fiqa_identity["query_count"],
                    "qrels": fiqa_identity["qrels_count"],
                },
                "parameters": {
                    "metric_ks": fiqa_identity["metric_ks"],
                    "run_top_k": fiqa_identity["run_top_k"],
                    "bm25": fiqa_identity["bm25"],
                    "dense": {
                        "batch_size": fiqa_dense["batch_size"],
                        "normalized": fiqa_dense["normalized"],
                        "search": fiqa_dense["search"],
                    },
                    "hybrid": fiqa_identity["hybrid"],
                    "reranker": {
                        "batch_size": fiqa_reranker["batch_size"],
                        "max_length": fiqa_reranker["max_length"],
                        "candidate_source": fiqa_reranker["candidate_source"],
                        "candidate_k": fiqa_reranker["candidate_k"],
                    },
                    "seed": fiqa_identity["seed"],
                    "test_split_tuning": fiqa_identity["test_split_tuning"],
                },
                "models": {
                    "embedding": _public_model(_mapping(fiqa_dense["model"], "fiqa dense model")),
                    "reranker": {
                        "name": "BAAI/bge-reranker-v2-m3",
                        **{
                            key: _mapping(fiqa_reranker["model"], "fiqa reranker model")[key]
                            for key in ("revision", "weight_sha256", "config_sha256")
                        },
                    },
                },
                "methods": fiqa_public_methods,
                "embedding_cache": {
                    "embedding_seconds": fiqa["embedding_cache"]["embedding_seconds"],
                    "matrix_bytes": fiqa["embedding_cache"]["matrix_bytes"],
                    "empty_document_vectors": fiqa["embedding_cache"]["empty_document_vectors"],
                },
            },
            "ragtruth": {
                "display_name": "RAGTruth",
                "task": "hallucination_detection",
                "source": "https://github.com/ParticleMedia/RAGTruth",
                "license": "MIT release; underlying source corpora retain their original rights",
                "citation": "Wu et al. (ACL 2024)",
                "dataset_revision": f"git:{truth_protocol['source_revision']}",
                "protocol": {
                    key: truth_protocol[key]
                    for key in (
                        "official_test_untouched",
                        "test_sources",
                        "test_responses",
                        "fit_sources",
                        "fit_responses",
                        "dev_sources",
                        "dev_responses",
                        "dev_fraction",
                        "seed",
                        "span_metric",
                        "implicit_true_policy",
                        "sentence_prediction_boundary",
                    )
                }
                | {"split_group": "source_group"},
                "model": _public_model(_mapping(truth_dense["model"], "ragtruth dense model")),
                "methods": _public_ragtruth_methods(
                    _mapping(ragtruth["methods"], "ragtruth.methods")
                ),
                "runtime": {
                    "accepted_first_run_wall_seconds": 614.65,
                    "cache_hit_wall_seconds": truth_runtime["wall_seconds"],
                    "cache_sha256": truth_dense["cache_sha256"],
                    "external_api_calls": truth_runtime["external_api_calls"],
                    "external_tokens": truth_runtime["external_tokens"],
                },
                "prediction_artifact_sha256": truth_artifacts["predictions_sha256"],
            },
            "ragbench": {
                "display_name": "RAGBench",
                "task": "trace_scoring",
                "source": "https://huggingface.co/datasets/galileo-ai/ragbench",
                "license": "CC BY 4.0; component-dataset notices still apply",
                "citation": "Friel, Belyi and Sanyal (2024)",
                "dataset_revision": f"git:{bench_protocol['source_revision']}",
                "protocol": {
                    key: bench_protocol[key]
                    for key in (
                        "subsets",
                        "official_splits",
                        "evaluated_splits",
                        "excluded_unlabeled_rows",
                        "train_role",
                        "validation_role",
                        "test_role",
                        "official_test_untouched",
                        "seed",
                        "max_text_chars",
                        "lexical_feature_names",
                        "external_judge_calls",
                        "gold_score_normalization",
                    )
                }
                | {
                    "duplicate_group_rows": bench_protocol["duplicate_source_id_rows"],
                },
                "model": _public_model(_mapping(bench_dense["model"], "ragbench dense model")),
                "methods": ragbench["methods"],
                "published_scorers": ragbench["published_scorers"],
                "runtime": {
                    "first_run_wall_seconds": bench_first_runtime["wall_seconds"],
                    "cache_hit_wall_seconds": bench_runtime["wall_seconds"],
                    "first_run_peak_working_set_bytes": bench_first_runtime[
                        "peak_working_set_bytes"
                    ],
                    "cache_sha256": bench_dense["cache_sha256"],
                    "external_api_calls": bench_runtime["external_api_calls"],
                    "external_tokens": bench_runtime["external_tokens"],
                },
                "prediction_artifact_sha256": bench_artifacts["predictions_sha256"],
            },
        },
        "limitations": [
            "All three public benchmarks are English and do not represent private Chinese traffic.",
            "FiQA is finance-domain retrieval and is restricted to non-commercial research use.",
            "RAGTruth sentence-boundary spans over-mark short hallucinated phrases.",
            "RAGBench adherence is highly imbalanced; F1 must not be used alone.",
            "Published values are offline research references, not production answer gates.",
        ],
    }
    validate_public_payload(payload)
    return payload


def validate_public_payload(payload: Mapping[str, Any]) -> None:
    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key.lower() in _FORBIDDEN_KEYS:
                    raise ValueError(f"forbidden public benchmark key: {key}")
                visit(nested)
        elif isinstance(value, list | tuple):
            for nested in value:
                visit(nested)

    visit(payload)
    encoded = json.dumps(payload, ensure_ascii=False).lower()
    for marker in _FORBIDDEN_TEXT:
        if marker in encoded:
            raise ValueError(f"forbidden public benchmark content marker: {marker}")


def _metric_rows(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add_metrics(
        dataset_id: str,
        method: str,
        task: str,
        slice_name: str,
        metrics: Mapping[str, Any],
    ) -> None:
        for metric, value in metrics.items():
            if isinstance(value, int | float) and not isinstance(value, bool):
                rows.append(
                    {
                        "dataset_id": dataset_id,
                        "method": method,
                        "task": task,
                        "slice": slice_name,
                        "metric": metric,
                        "value": repr(value),
                    }
                )

    datasets = _mapping(payload["datasets"], "datasets")
    fiqa = _mapping(datasets["beir-fiqa-2018"], "fiqa")
    for method_name, method_value in _mapping(fiqa["methods"], "fiqa.methods").items():
        method = _mapping(method_value, f"fiqa.methods.{method_name}")
        add_metrics("beir-fiqa-2018", method_name, "retrieval", "test", method["metrics"])
        add_metrics("beir-fiqa-2018", method_name, "latency", "test", method["latency"])

    truth = _mapping(datasets["ragtruth"], "ragtruth")
    for method_name, method_value in _mapping(truth["methods"], "ragtruth.methods").items():
        method = _mapping(method_value, f"ragtruth.methods.{method_name}")
        add_metrics("ragtruth", method_name, "response_level", "test", method["response_level"])
        add_metrics("ragtruth", method_name, "span_char", "test", method["span_char"])
        for task_name, task_metrics in _mapping(
            method["response_by_task"], f"ragtruth.methods.{method_name}.response_by_task"
        ).items():
            add_metrics(
                "ragtruth",
                method_name,
                "response_level",
                task_name,
                _mapping(task_metrics, f"ragtruth task {task_name}"),
            )

    bench = _mapping(datasets["ragbench"], "ragbench")
    for method_name, method_value in _mapping(bench["methods"], "ragbench.methods").items():
        method = _mapping(method_value, f"ragbench.methods.{method_name}")
        add_metrics("ragbench", method_name, "adherence", "test", method["adherence"])
        for target, metrics in _mapping(method["continuous"], "ragbench continuous").items():
            add_metrics(
                "ragbench",
                method_name,
                target,
                "test",
                _mapping(metrics, f"ragbench continuous {target}"),
            )
        for subset, metrics in _mapping(method["per_subset"], "ragbench per_subset").items():
            add_metrics(
                "ragbench",
                method_name,
                "subset_summary",
                subset,
                _mapping(metrics, f"ragbench subset {subset}"),
            )
    return rows


def export_results(
    *,
    fiqa_summary: Path,
    ragtruth_summary: Path,
    ragbench_summary: Path,
    ragbench_first_summary: Path,
    output_json: Path,
    output_csv: Path,
) -> None:
    payload = build_public_results(
        fiqa=load_json(fiqa_summary),
        ragtruth=load_json(ragtruth_summary),
        ragbench=load_json(ragbench_summary),
        ragbench_first=load_json(ragbench_first_summary),
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    rows = _metric_rows(payload)
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("dataset_id", "method", "task", "slice", "metric", "value"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export aggregate-only, path-free public benchmark results."
    )
    parser.add_argument("--fiqa-summary", type=Path, default=DEFAULT_FIQA_SUMMARY)
    parser.add_argument("--ragtruth-summary", type=Path, default=DEFAULT_RAGTRUTH_SUMMARY)
    parser.add_argument("--ragbench-summary", type=Path, default=DEFAULT_RAGBENCH_SUMMARY)
    parser.add_argument(
        "--ragbench-first-summary", type=Path, default=DEFAULT_RAGBENCH_FIRST_SUMMARY
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_ROOT / "results.json")
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_ROOT / "metrics.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export_results(
        fiqa_summary=args.fiqa_summary,
        ragtruth_summary=args.ragtruth_summary,
        ragbench_summary=args.ragbench_summary,
        ragbench_first_summary=args.ragbench_first_summary,
        output_json=args.output_json,
        output_csv=args.output_csv,
    )


if __name__ == "__main__":
    main()
