from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.evaluation import (  # noqa: E402
    BeirAdapter,
    BenchmarkDatasetRecord,
    BenchmarkLifecycle,
    BenchmarkManifest,
    RagBenchAdapter,
    RagBenchManifest,
    RagTruthAdapter,
    RagTruthManifest,
    hash_file,
    hash_files,
    load_benchmark_registry,
    ragbench_relative_files,
)

_DEFAULT_REGISTRY = _BACKEND_ROOT / "app" / "evaluation" / "registry.json"
_DEFAULT_DATA_ROOT = _BACKEND_ROOT / "datasets" / "benchmarks"
_MAX_ARCHIVE_FILES = 128
_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
_RAGTRUTH_FILES = ("response.jsonl", "source_info.jsonl")
_RAGBENCH_FILES = ragbench_relative_files()
_RAGBENCH_EXPECTED_SPLIT_COUNTS = {"train": 73286, "validation": 10293, "test": 11802}


def _dataset_root(data_root: Path, dataset_id: str) -> Path:
    return data_root.resolve() / dataset_id


def _raw_root(dataset_root: Path) -> Path:
    return dataset_root / "raw"


def _required_files(record_splits: list[str]) -> tuple[str, ...]:
    return (
        "corpus.jsonl",
        "queries.jsonl",
        *(f"qrels/{split}.tsv" for split in record_splits),
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(f"{destination.suffix}.part")
    partial.unlink(missing_ok=True)
    expected_bytes: int | None = None
    try:
        for _ in range(8):
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {"User-Agent": "Agentic/1.0 benchmark"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status not in {200, 206}:
                        raise ValueError(f"benchmark download returned HTTP {response.status}")
                    if offset and response.status != 206:
                        partial.unlink(missing_ok=True)
                        continue
                    content_range = response.headers.get("Content-Range")
                    content_length = response.headers.get("Content-Length")
                    if content_range:
                        expected_bytes = int(content_range.rsplit("/", maxsplit=1)[1])
                    elif content_length is not None:
                        expected_bytes = offset + int(content_length)
                    mode = "ab" if offset else "wb"
                    with partial.open(mode) as output:
                        shutil.copyfileobj(response, output, length=1024 * 1024)
            except (OSError, TimeoutError):
                continue
            actual_bytes = partial.stat().st_size
            if expected_bytes is not None and actual_bytes == expected_bytes:
                partial.replace(destination)
                return
            if expected_bytes is not None and actual_bytes > expected_bytes:
                raise ValueError("benchmark download exceeded the declared file size")
        actual_bytes = partial.stat().st_size if partial.exists() else 0
        raise ValueError(
            f"benchmark download was truncated after retries: expected {expected_bytes} "
            f"bytes, received {actual_bytes}"
        )
    finally:
        partial.unlink(missing_ok=True)


def _validated_members(archive: zipfile.ZipFile) -> tuple[zipfile.ZipInfo, ...]:
    members = tuple(archive.infolist())
    if len(members) > _MAX_ARCHIVE_FILES:
        raise ValueError("benchmark archive contains too many files")
    if sum(item.file_size for item in members) > _MAX_UNCOMPRESSED_BYTES:
        raise ValueError("benchmark archive is too large after extraction")
    for member in members:
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe archive member: {member.filename}")
        unix_mode = member.external_attr >> 16
        if unix_mode & 0o170000 == 0o120000:
            raise ValueError(f"symbolic links are not allowed: {member.filename}")
    return members


def _extract_beir_archive(archive_path: Path, raw_root: Path) -> None:
    if raw_root.exists():
        raise FileExistsError(f"raw dataset already exists: {raw_root}")
    raw_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agentic-benchmark-", dir=raw_root.parent) as temp:
        staging = Path(temp)
        with zipfile.ZipFile(archive_path) as archive:
            members = _validated_members(archive)
            archive.extractall(staging, members=members)
        roots = [item for item in staging.iterdir() if item.is_dir()]
        if len(roots) != 1:
            raise ValueError("expected exactly one dataset directory in BEIR archive")
        roots[0].replace(raw_root)


def _build_manifest(
    *,
    dataset_id: str,
    source_url: str,
    archive_path: Path,
    raw_root: Path,
    splits: list[str],
) -> BenchmarkManifest:
    adapter = BeirAdapter(raw_root)
    split_counts = adapter.validate(splits)
    required = _required_files(splits)
    return BenchmarkManifest(
        schema_version="1.0",
        dataset_id=dataset_id,
        lifecycle=BenchmarkLifecycle.FROZEN,
        source_url=source_url,
        archive_md5=hash_file(archive_path, "md5"),
        archive_sha256=hash_file(archive_path, "sha256"),
        archive_bytes=archive_path.stat().st_size,
        files=hash_files(raw_root, required),
        split_counts=split_counts,
    )


def _build_ragtruth_manifest(
    *,
    record: BenchmarkDatasetRecord,
    raw_root: Path,
) -> RagTruthManifest:
    if record.source_revision is None:
        raise ValueError("RAGTruth source revision is required")
    split_counts = RagTruthAdapter(raw_root).validate(record.splits)
    return RagTruthManifest(
        schema_version="1.0",
        dataset_id="ragtruth",
        lifecycle=BenchmarkLifecycle.FROZEN,
        source_url=record.source_url,
        source_revision=record.source_revision,
        files=hash_files(raw_root, _RAGTRUTH_FILES),
        file_bytes={
            relative_path: (raw_root / relative_path).stat().st_size
            for relative_path in _RAGTRUTH_FILES
        },
        split_counts=split_counts,
    )


def _build_ragbench_manifest(
    *,
    record: BenchmarkDatasetRecord,
    raw_root: Path,
) -> RagBenchManifest:
    if record.source_revision is None:
        raise ValueError("RAGBench source revision is required")
    split_counts = RagBenchAdapter(raw_root).validate()
    return RagBenchManifest(
        schema_version="1.0",
        dataset_id="ragbench",
        lifecycle="frozen",
        source_url=record.source_url,
        source_revision=record.source_revision,
        files=hash_files(raw_root, _RAGBENCH_FILES),
        file_bytes={
            relative_path: (raw_root / relative_path).stat().st_size
            for relative_path in _RAGBENCH_FILES
        },
        split_counts=split_counts,
        subsets=tuple(sorted({path.split("/", maxsplit=1)[0] for path in _RAGBENCH_FILES})),
    )


def _verify_ragbench_counts(
    manifest: RagBenchManifest,
    expected_responses: int | None,
) -> None:
    if expected_responses is not None and (
        manifest.split_counts["all"]["responses"] != expected_responses
    ):
        raise ValueError("downloaded RAGBench response count differs from the registry")
    for split, expected in _RAGBENCH_EXPECTED_SPLIT_COUNTS.items():
        if manifest.split_counts[split]["responses"] != expected:
            raise ValueError(f"downloaded RAGBench {split} count differs from the release")


def _verify_ragtruth_counts(manifest: RagTruthManifest, expected_responses: int | None) -> None:
    if expected_responses is not None and (
        manifest.split_counts["all"]["responses"] != expected_responses
    ):
        raise ValueError("downloaded RAGTruth response count differs from the registry")


def _verify_expected_counts(
    manifest: BenchmarkManifest,
    corpus: int | None,
    test: int | None,
) -> None:
    if corpus is not None and manifest.split_counts["all"]["corpus"] != corpus:
        raise ValueError("downloaded corpus count differs from the registry")
    if test is not None and manifest.split_counts["test"]["queries"] != test:
        raise ValueError("downloaded test query count differs from the registry")


def _download_ragtruth(
    record: BenchmarkDatasetRecord,
    root: Path,
    raw_root: Path,
    manifest_path: Path,
) -> int:
    if record.source_revision is None or set(record.download_files) != set(_RAGTRUTH_FILES):
        raise ValueError("approved RAGTruth dataset is missing fixed file metadata")
    if raw_root.exists():
        raise FileExistsError(
            "raw dataset exists without a frozen manifest; inspect it before retrying"
        )
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agentic-ragtruth-", dir=root) as temporary:
        staging = Path(temporary)
        for relative_path in _RAGTRUTH_FILES:
            url = record.download_files[relative_path]
            if not url.startswith("https://"):
                raise ValueError("RAGTruth download URLs must use HTTPS")
            _download(url, staging / relative_path)
        if sum((staging / item).stat().st_size for item in _RAGTRUTH_FILES) > (
            _MAX_UNCOMPRESSED_BYTES
        ):
            raise ValueError("RAGTruth release exceeds the local safety size limit")
        manifest = _build_ragtruth_manifest(record=record, raw_root=staging)
        _verify_ragtruth_counts(manifest, record.stats.response_count)
        staging.replace(raw_root)
    _write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    print(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def _download_ragbench(
    record: BenchmarkDatasetRecord,
    root: Path,
    raw_root: Path,
    manifest_path: Path,
) -> int:
    if record.source_revision is None or record.download_url is None:
        raise ValueError("approved RAGBench dataset is missing fixed source metadata")
    if raw_root.exists():
        raise FileExistsError(
            "raw dataset exists without a frozen manifest; inspect it before retrying"
        )
    base_url = record.download_url.rstrip("/")
    root.mkdir(parents=True, exist_ok=True)
    staging = root / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    for relative_path in _RAGBENCH_FILES:
        destination = staging / relative_path
        if destination.is_file() and destination.stat().st_size > 0:
            continue
        _download(f"{base_url}/{relative_path}?download=true", destination)
    total_bytes = sum((staging / item).stat().st_size for item in _RAGBENCH_FILES)
    if total_bytes > _MAX_UNCOMPRESSED_BYTES:
        raise ValueError("RAGBench release exceeds the local safety size limit")
    manifest = _build_ragbench_manifest(record=record, raw_root=staging)
    _verify_ragbench_counts(manifest, record.stats.response_count)
    staging.replace(raw_root)
    _write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    print(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def download_dataset(arguments: argparse.Namespace) -> int:
    registry, _ = load_benchmark_registry(Path(arguments.registry))
    record = registry.get(arguments.dataset)
    if record.lifecycle != BenchmarkLifecycle.APPROVED:
        raise PermissionError(f"{record.dataset_id} is not approved for download")

    root = _dataset_root(Path(arguments.data_root), record.dataset_id)
    raw_root = _raw_root(root)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        return verify_dataset(arguments)
    if record.adapter == "ragtruth":
        return _download_ragtruth(record, root, raw_root, manifest_path)
    if record.adapter == "ragbench":
        return _download_ragbench(record, root, raw_root, manifest_path)
    if record.adapter != "beir":
        raise ValueError(f"unsupported benchmark adapter: {record.adapter}")
    if record.download_url is None or record.expected_archive_md5 is None:
        raise ValueError("approved dataset is missing download metadata")

    archive_path = root / "archive" / f"{record.dataset_id}.zip"
    if raw_root.exists():
        raise FileExistsError(
            "raw dataset exists without a frozen manifest; inspect it before retrying"
        )

    if not archive_path.exists():
        _download(record.download_url, archive_path)
    actual_md5 = hash_file(archive_path, "md5")
    if actual_md5 != record.expected_archive_md5:
        raise ValueError(
            f"archive MD5 mismatch: expected {record.expected_archive_md5}, got {actual_md5}"
        )
    _extract_beir_archive(archive_path, raw_root)
    manifest = _build_manifest(
        dataset_id=record.dataset_id,
        source_url=record.download_url,
        archive_path=archive_path,
        raw_root=raw_root,
        splits=record.splits,
    )
    _verify_expected_counts(
        manifest,
        record.stats.corpus_count,
        record.stats.query_count,
    )
    _write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    print(json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def verify_dataset(arguments: argparse.Namespace) -> int:
    registry, _ = load_benchmark_registry(Path(arguments.registry))
    record = registry.get(arguments.dataset)
    root = _dataset_root(Path(arguments.data_root), record.dataset_id)
    raw_root = _raw_root(root)
    manifest_path = root / "manifest.json"
    if record.adapter == "ragtruth":
        frozen_ragtruth = RagTruthManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        current_ragtruth = _build_ragtruth_manifest(record=record, raw_root=raw_root)
        if current_ragtruth != frozen_ragtruth:
            raise ValueError("local RAGTruth files differ from the frozen manifest")
        _verify_ragtruth_counts(current_ragtruth, record.stats.response_count)
        print(json.dumps(current_ragtruth.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0
    if record.adapter == "ragbench":
        frozen_ragbench = RagBenchManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        current_ragbench = _build_ragbench_manifest(record=record, raw_root=raw_root)
        if current_ragbench != frozen_ragbench:
            raise ValueError("local RAGBench files differ from the frozen manifest")
        _verify_ragbench_counts(current_ragbench, record.stats.response_count)
        print(json.dumps(current_ragbench.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0

    archive_path = root / "archive" / f"{record.dataset_id}.zip"
    frozen = BenchmarkManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    current = _build_manifest(
        dataset_id=record.dataset_id,
        source_url=cast(str, record.download_url),
        archive_path=archive_path,
        raw_root=raw_root,
        splits=record.splits,
    )
    if current != frozen:
        raise ValueError("local benchmark files differ from the frozen manifest")
    if record.expected_archive_md5 and current.archive_md5 != record.expected_archive_md5:
        raise ValueError("local archive differs from the registry checksum")
    _verify_expected_counts(current, record.stats.corpus_count, record.stats.query_count)
    print(json.dumps(current.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def show_registry(arguments: argparse.Namespace) -> int:
    registry, digest = load_benchmark_registry(Path(arguments.registry))
    payload = {
        "sha256": digest,
        "datasets": [
            {
                "dataset_id": item.dataset_id,
                "task": item.task,
                "lifecycle": item.lifecycle,
                "license": item.license_name,
                "approval_scope": item.approval_scope,
            }
            for item in registry.datasets
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage approved public RAG benchmarks")
    parser.add_argument("--registry", default=str(_DEFAULT_REGISTRY))
    parser.add_argument("--data-root", default=str(_DEFAULT_DATA_ROOT))
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="validate and show registry metadata")
    catalog.set_defaults(handler=show_registry)

    download = subparsers.add_parser("download", help="download, verify and freeze one dataset")
    download.add_argument("dataset")
    download.set_defaults(handler=download_dataset)

    verify = subparsers.add_parser("verify", help="verify a frozen local dataset")
    verify.add_argument("dataset")
    verify.set_defaults(handler=verify_dataset)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
