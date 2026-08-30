from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

import numpy as np
import psutil  # type: ignore[import-untyped]
import sklearn  # type: ignore[import-untyped]
import torch
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression, Ridge  # type: ignore[import-untyped]
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    RAGBENCH_SUBSETS,
    RagBenchAdapter,
    RagBenchExample,
    RagBenchManifest,
    binary_metrics,
    expected_calibration_error,
    hash_file,
    hash_files,
    ragbench_relative_files,
)
from app.evaluation.ragbench_scoring import (  # noqa: E402
    LEXICAL_FEATURE_NAMES,
    clip_predictions,
    continuous_metrics,
    lexical_trace_scores,
    ragbench_lexical_features,
    tune_binary_threshold,
)
from app.evaluation.run_store import write_json_atomic  # noqa: E402

DATASET_ROOT = _BACKEND_ROOT / "datasets" / "benchmarks" / "ragbench"
DEFAULT_OUTPUT = DATASET_ROOT / "runs" / "week05-day04-ragbench"
DEFAULT_EMBEDDING_MODEL = _REPO_ROOT / "data" / "models" / "embedding" / "bge-m3"
EMBEDDING_BATCH_SIZE = 16
EXAMPLE_BATCH_SIZE = 64
MAX_TEXT_CHARS = 8000
SEED = 42
CONTINUOUS_LABELS = ("relevance", "utilization", "completeness")
DENSE_FEATURE_NAMES = (
    "question_context_dense",
    "response_context_dense",
    "question_response_dense",
)
PUBLISHED_TARGETS = {
    "trulens_groundedness": "adherence",
    "ragas_faithfulness": "adherence",
    "gpt3_adherence": "adherence",
    "trulens_context_relevance": "relevance",
    "ragas_context_relevance": "relevance",
    "gpt3_context_relevance": "relevance",
    "gpt35_utilization": "utilization",
}


@dataclass(frozen=True, slots=True)
class CompactDataset:
    ids: tuple[str, ...]
    subsets: tuple[str, ...]
    splits: tuple[str, ...]
    lexical_features: NDArray[np.float64]
    lexical_scores: dict[str, NDArray[np.float64]]
    adherence: NDArray[np.int64]
    continuous: dict[str, NDArray[np.float64]]
    published: dict[str, NDArray[np.float64]]
    gold_score_normalization_counts: dict[str, int] = dataclass_field(default_factory=dict)
    duplicate_source_id_rows: int = 0
    excluded_unlabeled_rows: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic RAGBench TRACe scorer baselines"
    )
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    parser.add_argument("--embedding-model", type=Path, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--embedding-batch-size", type=int, default=EMBEDDING_BATCH_SIZE)
    parser.add_argument("--example-batch-size", type=int, default=EXAMPLE_BATCH_SIZE)
    parser.add_argument("--max-text-chars", type=int, default=MAX_TEXT_CHARS)
    parser.add_argument("--force-dense", action="store_true")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.embedding_batch_size < 1 or arguments.example_batch_size < 1:
        raise ValueError("batch sizes must be positive")
    if arguments.max_text_chars < 256:
        raise ValueError("max text chars must be at least 256")

    started = time.perf_counter()
    process = psutil.Process()
    dataset_root = arguments.dataset_root.resolve()
    manifest = verify_frozen_dataset(dataset_root)
    adapter = RagBenchAdapter(dataset_root / "raw")
    compact = build_compact_dataset(adapter)
    masks = {
        split: np.asarray([value == split for value in compact.splits], dtype=np.bool_)
        for split in ("train", "validation", "test")
    }
    if any(not np.any(mask) for mask in masks.values()):
        raise ValueError("RAGBench train, validation and test splits are required")

    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    dense_started = time.perf_counter()
    dense_features, dense_metadata = load_or_compute_dense_features(
        adapter=adapter,
        row_count=len(compact.ids),
        model_path=arguments.embedding_model.resolve(),
        output=output,
        device_preference=arguments.device,
        embedding_batch_size=arguments.embedding_batch_size,
        example_batch_size=arguments.example_batch_size,
        max_text_chars=arguments.max_text_chars,
        manifest=manifest,
        force=arguments.force_dense,
    )
    dense_seconds = time.perf_counter() - dense_started
    full_features = np.column_stack((compact.lexical_features, dense_features))

    methods: dict[str, dict[str, Any]] = {}
    predictions: dict[str, dict[str, NDArray[np.float64]]] = {}

    lexical_predictions = {
        label: compact.lexical_scores[label] for label in ("adherence", *CONTINUOUS_LABELS)
    }
    methods["lexical_heuristic"] = evaluate_method(
        compact=compact,
        scores=lexical_predictions,
        masks=masks,
    )
    predictions["lexical_heuristic"] = lexical_predictions

    lexical_linear_scores, lexical_linear_meta = fit_linear_trace_models(
        features=compact.lexical_features,
        compact=compact,
        masks=masks,
    )
    methods["lexical_linear"] = evaluate_method(
        compact=compact,
        scores=lexical_linear_scores,
        masks=masks,
    )
    methods["lexical_linear"]["model"] = lexical_linear_meta
    predictions["lexical_linear"] = lexical_linear_scores

    dense_linear_scores, dense_linear_meta = fit_linear_trace_models(
        features=full_features,
        compact=compact,
        masks=masks,
    )
    methods["lexical_dense_linear"] = evaluate_method(
        compact=compact,
        scores=dense_linear_scores,
        masks=masks,
    )
    methods["lexical_dense_linear"]["model"] = dense_linear_meta
    predictions["lexical_dense_linear"] = dense_linear_scores

    published = evaluate_published_scorers(compact=compact, masks=masks)
    prediction_path = output / "test-predictions.jsonl"
    write_predictions(
        prediction_path,
        compact=compact,
        masks=masks,
        predictions=predictions,
    )

    wall_seconds = time.perf_counter() - started
    summary = {
        "schema_version": "1.0",
        "benchmark": "ragbench",
        "protocol": {
            "source_revision": manifest.source_revision,
            "dataset_files": manifest.files,
            "subsets": list(RAGBENCH_SUBSETS),
            "official_splits": {
                split: manifest.split_counts[split]["responses"]
                for split in ("train", "validation", "test")
            },
            "evaluated_splits": {split: int(np.sum(mask)) for split, mask in masks.items()},
            "excluded_unlabeled_rows": compact.excluded_unlabeled_rows,
            "train_role": "fit classic models",
            "validation_role": "threshold and alpha selection only",
            "test_role": "final evaluation only",
            "official_test_untouched": True,
            "seed": SEED,
            "max_text_chars": arguments.max_text_chars,
            "lexical_feature_names": list(LEXICAL_FEATURE_NAMES),
            "external_judge_calls": 0,
            "gold_score_normalization": {
                "rule": "clip official continuous labels to [0, 1]",
                "counts": compact.gold_score_normalization_counts,
            },
            "duplicate_source_id_rows": compact.duplicate_source_id_rows,
        },
        "methods": methods,
        "published_scorers": published,
        "dense": {
            **dense_metadata,
            "wall_seconds": dense_seconds,
            "feature_names": list(DENSE_FEATURE_NAMES),
        },
        "runtime": {
            "wall_seconds": wall_seconds,
            "peak_working_set_bytes": process.memory_info().peak_wset,
            "hardware": hardware_info(),
            "external_api_calls": 0,
            "external_tokens": 0,
            "new_model_downloads": 0,
        },
        "artifacts": {
            "predictions": prediction_path.name,
            "predictions_sha256": hash_file(prediction_path),
        },
    }
    write_json_atomic(output / "summary.json", summary)
    print(json.dumps(console_summary(summary), ensure_ascii=False, indent=2))
    print(f"summary: {output / 'summary.json'}")
    return 0


def verify_frozen_dataset(dataset_root: Path) -> RagBenchManifest:
    manifest_path = dataset_root / "manifest.json"
    manifest = RagBenchManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    raw_root = dataset_root / "raw"
    current_files = hash_files(raw_root, ragbench_relative_files())
    if current_files != manifest.files:
        raise ValueError("local RAGBench files differ from the frozen manifest")
    current_bytes = {
        relative_path: (raw_root / relative_path).stat().st_size
        for relative_path in ragbench_relative_files()
    }
    if current_bytes != manifest.file_bytes:
        raise ValueError("local RAGBench file sizes differ from the frozen manifest")
    return manifest


def has_complete_gold(example: RagBenchExample) -> bool:
    labels = (
        example.adherence_score,
        example.relevance_score,
        example.utilization_score,
        example.completeness_score,
    )
    if all(value is None for value in labels):
        return False
    if any(value is None for value in labels):
        raise ValueError("RAGBench row has partially missing gold labels")
    return True


def build_compact_dataset(adapter: RagBenchAdapter) -> CompactDataset:
    ids: list[str] = []
    subsets: list[str] = []
    splits: list[str] = []
    feature_rows: list[tuple[float, ...]] = []
    lexical_scores: dict[str, list[float]] = {
        label: [] for label in ("adherence", *CONTINUOUS_LABELS)
    }
    adherence: list[int] = []
    continuous: dict[str, list[float]] = {label: [] for label in CONTINUOUS_LABELS}
    normalization_counts = {label: 0 for label in CONTINUOUS_LABELS}
    source_identities: set[tuple[str, str, str]] = set()
    duplicate_source_id_rows = 0
    excluded_unlabeled_rows = 0
    published: dict[str, list[float]] = {field: [] for field in PUBLISHED_TARGETS}

    for example in adapter.iter_examples():
        source_identity = (example.subset, example.split, example.example_id)
        duplicate_source_id_rows += int(source_identity in source_identities)
        source_identities.add(source_identity)
        if not has_complete_gold(example):
            excluded_unlabeled_rows += 1
            continue
        features = ragbench_lexical_features(
            question=example.question,
            documents=example.documents,
            response=example.response,
        )
        scores = lexical_trace_scores(features)
        ids.append(f"{example.subset}/{example.split}/{example.row_index}:{example.example_id}")
        subsets.append(example.subset)
        splits.append(example.split)
        feature_rows.append(features)
        for label, score in scores.items():
            lexical_scores[label].append(score)
        assert example.adherence_score is not None
        assert example.relevance_score is not None
        assert example.utilization_score is not None
        assert example.completeness_score is not None
        adherence.append(int(example.adherence_score))
        raw_scores = {
            "relevance": example.relevance_score,
            "utilization": example.utilization_score,
            "completeness": example.completeness_score,
        }
        for label, raw_score in raw_scores.items():
            normalized = min(max(raw_score, 0.0), 1.0)
            continuous[label].append(normalized)
            normalization_counts[label] += int(normalized != raw_score)
        for field in PUBLISHED_TARGETS:
            value = example.published_scores[field]
            published[field].append(float("nan") if value is None else value)

    if not ids:
        raise ValueError("RAGBench release is empty")
    return CompactDataset(
        ids=tuple(ids),
        subsets=tuple(subsets),
        splits=tuple(splits),
        lexical_features=np.asarray(feature_rows, dtype=np.float64),
        lexical_scores={
            label: np.asarray(values, dtype=np.float64) for label, values in lexical_scores.items()
        },
        adherence=np.asarray(adherence, dtype=np.int64),
        continuous={
            label: np.asarray(values, dtype=np.float64) for label, values in continuous.items()
        },
        published={
            field: np.asarray(values, dtype=np.float64) for field, values in published.items()
        },
        gold_score_normalization_counts=normalization_counts,
        duplicate_source_id_rows=duplicate_source_id_rows,
        excluded_unlabeled_rows=excluded_unlabeled_rows,
    )


def load_or_compute_dense_features(
    *,
    adapter: RagBenchAdapter,
    row_count: int,
    model_path: Path,
    output: Path,
    device_preference: str,
    embedding_batch_size: int,
    example_batch_size: int,
    max_text_chars: int,
    manifest: RagBenchManifest,
    force: bool,
) -> tuple[NDArray[np.float64], dict[str, Any]]:
    identity = model_identity(model_path)
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "manifest_files": manifest.files,
                "model": identity,
                "max_text_chars": max_text_chars,
                "feature_names": DENSE_FEATURE_NAMES,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cache_path = output / "dense-features.npz"
    if cache_path.exists() and not force:
        with np.load(cache_path, allow_pickle=False) as payload:
            saved_key = str(payload["cache_key"].item())
            features = np.asarray(payload["features"], dtype=np.float64)
        if saved_key == cache_key and features.shape == (row_count, len(DENSE_FEATURE_NAMES)):
            return features, {
                "cache": "hit",
                "cache_key": cache_key,
                "cache_sha256": hash_file(cache_path),
                "model": identity,
                "embedding_batch_size": embedding_batch_size,
                "example_batch_size": example_batch_size,
            }

    device = resolve_device(device_preference)
    model_kwargs: dict[str, Any] | None = None
    if device == "cuda":
        model_kwargs = {"torch_dtype": torch.float16}
    model = SentenceTransformer(
        str(model_path),
        device=device,
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs=model_kwargs,
    )
    batches: list[NDArray[np.float64]] = []
    pending: list[RagBenchExample] = []
    for example in adapter.iter_examples():
        if not has_complete_gold(example):
            continue
        pending.append(example)
        if len(pending) >= example_batch_size:
            batches.append(
                encode_dense_batch(
                    model,
                    pending,
                    embedding_batch_size=embedding_batch_size,
                    max_text_chars=max_text_chars,
                )
            )
            pending.clear()
    if pending:
        batches.append(
            encode_dense_batch(
                model,
                pending,
                embedding_batch_size=embedding_batch_size,
                max_text_chars=max_text_chars,
            )
        )
    features = np.vstack(batches)
    if features.shape != (row_count, len(DENSE_FEATURE_NAMES)):
        raise ValueError("RAGBench dense feature count differs from lexical rows")
    temporary = cache_path.with_suffix(".npz.tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, cache_key=np.asarray(cache_key), features=features)
    temporary.replace(cache_path)
    return features, {
        "cache": "miss",
        "cache_key": cache_key,
        "cache_sha256": hash_file(cache_path),
        "model": identity,
        "device": device,
        "embedding_batch_size": embedding_batch_size,
        "example_batch_size": example_batch_size,
    }


def encode_dense_batch(
    model: SentenceTransformer,
    examples: list[RagBenchExample],
    *,
    embedding_batch_size: int,
    max_text_chars: int,
) -> NDArray[np.float64]:
    texts: list[str] = []
    for example in examples:
        texts.extend(
            (
                example.question[:max_text_chars],
                " ".join(example.documents)[:max_text_chars],
                example.response[:max_text_chars],
            )
        )
    vectors = np.asarray(
        model.encode(
            texts,
            batch_size=embedding_batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ),
        dtype=np.float64,
    ).reshape(len(examples), 3, -1)
    return np.column_stack(
        (
            np.sum(vectors[:, 0, :] * vectors[:, 1, :], axis=1),
            np.sum(vectors[:, 2, :] * vectors[:, 1, :], axis=1),
            np.sum(vectors[:, 0, :] * vectors[:, 2, :], axis=1),
        )
    )


def fit_linear_trace_models(
    *,
    features: NDArray[np.float64],
    compact: CompactDataset,
    masks: dict[str, NDArray[np.bool_]],
) -> tuple[dict[str, NDArray[np.float64]], dict[str, Any]]:
    train = masks["train"]
    validation = masks["validation"]
    logistic = make_pipeline(
        StandardScaler(),
        LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=SEED,
        ),
    )
    logistic.fit(features[train], compact.adherence[train])
    adherence_scores = np.asarray(logistic.predict_proba(features)[:, 1], dtype=np.float64)

    continuous_scores: dict[str, NDArray[np.float64]] = {}
    selected_alphas: dict[str, float] = {}
    for label in CONTINUOUS_LABELS:
        target = compact.continuous[label]
        best_key = (float("inf"), float("inf"))
        best_predictions: NDArray[np.float64] | None = None
        best_alpha = 1.0
        for alpha in (0.1, 1.0, 10.0, 100.0):
            model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
            model.fit(features[train], target[train])
            predictions = np.asarray(model.predict(features), dtype=np.float64)
            validation_metrics = continuous_metrics(
                target[validation].tolist(),
                clip_predictions(predictions[validation].tolist()),
            )
            key = (validation_metrics.rmse, alpha)
            if key < best_key:
                best_key = key
                best_predictions = predictions
                best_alpha = alpha
        if best_predictions is None:
            raise RuntimeError(f"failed to fit RAGBench {label} model")
        continuous_scores[label] = np.asarray(
            clip_predictions(best_predictions.tolist()),
            dtype=np.float64,
        )
        selected_alphas[label] = best_alpha
    return {
        "adherence": adherence_scores,
        **continuous_scores,
    }, {
        "algorithm": "StandardScaler + LogisticRegression/Ridge",
        "adherence_class_weight": "balanced",
        "ridge_alpha_grid": [0.1, 1.0, 10.0, 100.0],
        "selected_alphas": selected_alphas,
        "feature_count": int(features.shape[1]),
    }


def evaluate_method(
    *,
    compact: CompactDataset,
    scores: dict[str, NDArray[np.float64]],
    masks: dict[str, NDArray[np.bool_]],
) -> dict[str, Any]:
    validation = masks["validation"]
    test = masks["test"]
    threshold = tune_binary_threshold(
        compact.adherence[validation].tolist(),
        scores["adherence"][validation].tolist(),
    )
    result: dict[str, Any] = {
        "adherence": adherence_metrics(
            compact.adherence[test],
            scores["adherence"][test],
            threshold,
        ),
        "continuous": {
            label: asdict(
                continuous_metrics(
                    compact.continuous[label][test].tolist(),
                    scores[label][test].tolist(),
                )
            )
            for label in CONTINUOUS_LABELS
        },
        "per_subset": {},
    }
    result["adherence"]["threshold"] = threshold
    for subset in RAGBENCH_SUBSETS:
        subset_mask = np.logical_and(
            test,
            np.asarray([value == subset for value in compact.subsets], dtype=np.bool_),
        )
        result["per_subset"][subset] = {
            "count": int(np.sum(subset_mask)),
            "adherence_f1": adherence_metrics(
                compact.adherence[subset_mask],
                scores["adherence"][subset_mask],
                threshold,
            )["f1"],
            **{
                f"{label}_rmse": asdict(
                    continuous_metrics(
                        compact.continuous[label][subset_mask].tolist(),
                        scores[label][subset_mask].tolist(),
                    )
                )["rmse"]
                for label in CONTINUOUS_LABELS
            },
        }
    return result


def adherence_metrics(
    labels: NDArray[np.int64],
    scores: NDArray[np.float64],
    threshold: float,
) -> dict[str, Any]:
    label_list = labels.tolist()
    score_list = scores.tolist()
    predictions = [int(score >= threshold) for score in score_list]
    confusion = binary_metrics(label_list, predictions)
    return {
        **asdict(confusion),
        "auroc": (float(roc_auc_score(labels, scores)) if len(set(label_list)) > 1 else None),
        "auprc": (float(average_precision_score(labels, scores)) if any(label_list) else None),
        "brier": float(brier_score_loss(labels, scores)),
        "ece_10": expected_calibration_error(label_list, score_list, bins=10),
        "count": len(label_list),
        "positive_rate": sum(label_list) / len(label_list),
        "predicted_positive_rate": sum(predictions) / len(predictions),
    }


def evaluate_published_scorers(
    *,
    compact: CompactDataset,
    masks: dict[str, NDArray[np.bool_]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field, target in PUBLISHED_TARGETS.items():
        values = compact.published[field]
        finite = np.isfinite(values)
        in_range = np.logical_and(finite, np.logical_and(values >= 0.0, values <= 1.0))
        validation = np.logical_and(masks["validation"], in_range)
        test = np.logical_and(masks["test"], in_range)
        validation_out_of_range = np.logical_and(
            masks["validation"],
            np.logical_and(finite, np.logical_not(in_range)),
        )
        test_out_of_range = np.logical_and(
            masks["test"],
            np.logical_and(finite, np.logical_not(in_range)),
        )
        common = {
            "target": target,
            "validation_count": int(np.sum(validation)),
            "test_count": int(np.sum(test)),
            "validation_out_of_range": int(np.sum(validation_out_of_range)),
            "test_out_of_range": int(np.sum(test_out_of_range)),
        }
        if not np.any(test):
            result[field] = {
                **common,
                "status": "insufficient published test values",
            }
            continue
        if target == "adherence":
            if np.any(validation):
                threshold = tune_binary_threshold(
                    compact.adherence[validation].tolist(),
                    values[validation].tolist(),
                )
                threshold_source = "validation_f1"
            else:
                threshold = 0.5
                threshold_source = "fixed_0.5_no_validation_values"
            metrics = adherence_metrics(
                compact.adherence[test],
                values[test],
                threshold,
            )
            metrics["threshold"] = threshold
            metrics["threshold_source"] = threshold_source
        else:
            metrics = asdict(
                continuous_metrics(
                    compact.continuous[target][test].tolist(),
                    values[test].tolist(),
                )
            )
        result[field] = {
            **common,
            "metrics": metrics,
        }
    return result


def write_predictions(
    path: Path,
    *,
    compact: CompactDataset,
    masks: dict[str, NDArray[np.bool_]],
    predictions: dict[str, dict[str, NDArray[np.float64]]],
) -> None:
    temporary = path.with_suffix(".jsonl.tmp")
    test_indices = np.flatnonzero(masks["test"])
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        for position in test_indices:
            index = int(position)
            payload = {
                "id": compact.ids[index],
                "subset": compact.subsets[index],
                "split": "test",
                "gold": {
                    "adherence": int(compact.adherence[index]),
                    **{
                        label: float(compact.continuous[label][index])
                        for label in CONTINUOUS_LABELS
                    },
                },
                "scores": {
                    method: {
                        label: float(method_scores[label][index])
                        for label in ("adherence", *CONTINUOUS_LABELS)
                    }
                    for method, method_scores in predictions.items()
                },
            }
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + chr(10))
    temporary.replace(path)


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
    return {
        "path": str(model_path),
        "revision": revision,
        "weight_sha256": weight_sha256,
        "config_sha256": hash_file(model_path / "config.json"),
    }


def resolve_device(preference: str) -> str:
    if preference == "cpu":
        return "cpu"
    if preference == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    return "cuda" if torch.cuda.is_available() else "cpu"


def hardware_info() -> dict[str, Any]:
    gpu = None
    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        gpu = {
            "name": properties.name,
            "total_memory_bytes": properties.total_memory,
            "cuda_runtime": torch.version.cuda,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        }
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "torch": torch.__version__,
        "sklearn": sklearn.__version__,
        "gpu": gpu,
    }


def console_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        method: {
            "adherence_f1": payload["adherence"]["f1"],
            "adherence_auroc": payload["adherence"]["auroc"],
            **{
                f"{label}_spearman": payload["continuous"][label]["spearman"]
                for label in CONTINUOUS_LABELS
            },
        }
        for method, payload in summary["methods"].items()
    }


if __name__ == "__main__":
    raise SystemExit(main())
