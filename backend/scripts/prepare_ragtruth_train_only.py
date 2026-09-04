from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import RagTruthAdapter, RagTruthManifest, hash_file  # noqa: E402

DATASET_ROOT = _BACKEND_ROOT / "datasets" / "benchmarks" / "ragtruth"
DEFAULT_OUTPUT = DATASET_ROOT / "derived" / "train-only"
TRANSFORM_ID = "ragtruth-stream-filter-train-v1"

_SPLIT_RE = re.compile(r'(?<!\\)"split"\s*:\s*"([^"\\]+)"')
_SOURCE_ID_RE = re.compile(r'(?<!\\)"source_id"\s*:\s*"([^"\\]+)"')


def _extract_single_field(
    line: str,
    pattern: re.Pattern[str],
    field_name: str,
    path: Path,
    line_number: int,
) -> str:
    matches = pattern.findall(line)
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one top-level {field_name} at line {line_number}: {path}"
        )
    return str(matches[0])


def _parse_object(line: str, path: Path, line_number: int) -> dict[str, Any]:
    try:
        payload: Any = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid selected JSONL row at line {line_number}: {path}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"selected JSONL row {line_number} is not an object: {path}")
    return payload


def _copy_train_responses(source: Path, target: Path) -> set[str]:
    train_source_ids: set[str] = set()
    response_ids: set[str] = set()
    with (
        source.open("r", encoding="utf-8", newline="") as input_handle,
        target.open("w", encoding="utf-8", newline="") as output_handle,
    ):
        for line_number, line in enumerate(input_handle, start=1):
            if not line.strip():
                continue
            split = _extract_single_field(line, _SPLIT_RE, "split", source, line_number)
            if split == "test":
                continue
            if split != "train":
                raise ValueError(f"unexpected RAGTruth split at line {line_number}: {split}")

            payload = _parse_object(line, source, line_number)
            if payload.get("split") != "train":
                raise ValueError(f"split scanner mismatch at line {line_number}: {source}")
            source_id = str(payload.get("source_id") or "")
            response_id = str(payload.get("id") or "")
            if not source_id or not response_id:
                raise ValueError(f"selected response is missing an identity at line {line_number}")
            if response_id in response_ids:
                raise ValueError("train response ids must be unique")
            response_ids.add(response_id)
            train_source_ids.add(source_id)
            output_handle.write(line)
    if not response_ids:
        raise ValueError("RAGTruth train selection is empty")
    return train_source_ids


def _copy_train_sources(source: Path, target: Path, train_source_ids: set[str]) -> None:
    copied_source_ids: set[str] = set()
    with (
        source.open("r", encoding="utf-8", newline="") as input_handle,
        target.open("w", encoding="utf-8", newline="") as output_handle,
    ):
        for line_number, line in enumerate(input_handle, start=1):
            if not line.strip():
                continue
            source_id = _extract_single_field(
                line, _SOURCE_ID_RE, "source_id", source, line_number
            )
            if source_id not in train_source_ids:
                continue

            payload = _parse_object(line, source, line_number)
            if str(payload.get("source_id") or "") != source_id:
                raise ValueError(f"source scanner mismatch at line {line_number}: {source}")
            if source_id in copied_source_ids:
                raise ValueError("selected train source ids must be unique")
            copied_source_ids.add(source_id)
            output_handle.write(line)

    missing = train_source_ids.difference(copied_source_ids)
    if missing:
        raise ValueError(f"selected responses reference {len(missing)} missing train sources")


def _verify_parent_files(raw_root: Path, manifest: RagTruthManifest) -> None:
    required = {"response.jsonl", "source_info.jsonl"}
    if set(manifest.files) != required:
        raise ValueError("RAGTruth parent manifest must freeze exactly the two approved files")
    for relative_path, expected_hash in manifest.files.items():
        path = raw_root / relative_path
        if not path.is_file():
            raise FileNotFoundError(path)
        if hash_file(path) != expected_hash:
            raise ValueError(f"RAGTruth parent file differs from its frozen hash: {relative_path}")


def derive_train_only(
    raw_root: Path,
    output_root: Path,
    parent_manifest: RagTruthManifest,
    transform_path: Path,
) -> dict[str, Any]:
    """Build an aggregate-only, frozen train view without decoding excluded response rows."""
    raw_root = raw_root.resolve()
    output_root = output_root.resolve()
    transform_path = transform_path.resolve()
    _verify_parent_files(raw_root, parent_manifest)
    if output_root.exists():
        raise FileExistsError(f"refusing to replace existing derived dataset: {output_root}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".train-only-", dir=output_root.parent))
    try:
        train_source_ids = _copy_train_responses(
            raw_root / "response.jsonl", staging / "response.jsonl"
        )
        _copy_train_sources(
            raw_root / "source_info.jsonl",
            staging / "source_info.jsonl",
            train_source_ids,
        )

        observed = RagTruthAdapter(staging).validate(("train",))["train"]
        expected = dict(parent_manifest.split_counts["train"])
        if observed != expected:
            raise ValueError(
                f"derived train counts differ from frozen parent manifest: {observed} != {expected}"
            )

        relative_files = ("response.jsonl", "source_info.jsonl")
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "dataset_id": "ragtruth-train-only",
            "lifecycle": "frozen",
            "derivation": TRANSFORM_ID,
            "parent": {
                "dataset_id": parent_manifest.dataset_id,
                "source_revision": parent_manifest.source_revision,
                "files": dict(sorted(parent_manifest.files.items())),
            },
            "files": {name: hash_file(staging / name) for name in relative_files},
            "file_bytes": {name: (staging / name).stat().st_size for name in relative_files},
            "split_counts": {"train": expected},
            "transform": {
                "path": transform_path.relative_to(_REPO_ROOT).as_posix(),
                "sha256": hash_file(transform_path),
            },
            "boundary": {
                "selected_split": "train",
                "excluded_rows_decoded": False,
                "sample_payloads_recorded": False,
            },
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staging, output_root)
        return payload
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _load_parent_manifest(path: Path) -> RagTruthManifest:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    return RagTruthManifest.model_validate(payload)


def _counts_text(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the approved frozen RAGTruth train-only derived snapshot"
    )
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    dataset_root = args.dataset_root.resolve()
    parent_manifest = _load_parent_manifest(dataset_root / "manifest.json")
    payload = derive_train_only(
        dataset_root / "raw",
        args.output,
        parent_manifest,
        Path(__file__),
    )
    counts = payload["split_counts"]["train"]
    print(f"created={args.output.resolve()}")
    print(f"train_counts={_counts_text(counts)}")
    print(f"manifest_sha256={hash_file(args.output.resolve() / 'manifest.json')}")


if __name__ == "__main__":
    main()
