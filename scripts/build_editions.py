"""Build reviewable product/research source archives; never bundle local runtime data."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
COMMON_FILES = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "backend/alembic.ini",
    "scripts/install.ps1",
)
SKIP_PARTS = {
    "__pycache__",
    "node_modules",
    ".venv",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
}
FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".parquet",
    ".jsonl",
    ".safetensors",
    ".pt",
    ".pth",
    ".onnx",
    ".log",
}


def safe_file(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_PARTS for part in rel.parts):
        return False
    if path.suffix in FORBIDDEN_SUFFIXES or (
        path.name.startswith(".env") and path.name != ".env.example"
    ):
        return False
    # Never traverse an asset into the archive through a symlink or Windows junction.
    for part in (path, *path.parents):
        if part == root:
            break
        info = part.lstat()
        if (
            part.is_symlink()
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError(f"linked source is not permitted: {rel.as_posix()}")
    return path.is_file()


def source_files(root: Path, edition: str) -> list[Path]:
    paths = [root / name for name in COMMON_FILES]
    paths += list((root / "frontend").glob("*"))
    for folder in ("backend/app", "backend/migrations", "frontend/src", "frontend/public"):
        paths += list((root / folder).rglob("*"))
    if edition == "research":
        paths += [
            root / name
            for name in (
                "README.en.md",
                "CHANGELOG.md",
                "CONTRIBUTING.md",
                "TECHNICAL_DOCUMENTATION.md",
            )
        ]
        for folder in (
            "backend/scripts",
            "backend/tests",
            "benchmarks",
            "docs",
            "scripts",
            "frontend/e2e",
        ):
            paths += list((root / folder).rglob("*"))
    return sorted(
        {
            path
            for path in paths
            if safe_file(path, root)
            and not (
                edition == "product"
                and path.relative_to(root).as_posix().startswith("backend/app/evaluation/")
            )
        }
    )


def build(root: Path, destination: Path, edition: str, label: str) -> Path:
    if edition not in {"product", "research"} or not re.fullmatch(r"[A-Za-z0-9._-]+", label):
        raise ValueError("invalid edition or archive label")
    contents = {
        path.relative_to(root).as_posix(): path.read_bytes() for path in source_files(root, edition)
    }
    readme = (root / "docs/editions" / f"{edition}.md").read_text(encoding="utf-8")
    contents["README.md"] = readme.replace("](../../", "](").encode("utf-8")
    contents[".env.example"] = re.sub(
        rb"(?m)^AGENTIC_EDITION=(?:product|research)(?=\r?$)",
        f"AGENTIC_EDITION={edition}".encode(),
        contents[".env.example"],
    )
    contents["backend/app/core/distribution.py"] = (
        "from typing import Literal\n\n"
        f'DEFAULT_EDITION: Literal["product", "research"] = "{edition}"\n'
        f"RESEARCH_AVAILABLE = {edition == 'research'}\n"
    ).encode()
    if edition == "product":
        contents["frontend/README.md"] = (
            "# Agentic 产品版前端\n\n"
            "安装、配置与启动见[产品版说明](../README.md)。\n\n"
            "在 frontend 目录使用 `npm ci` 安装依赖，`npm run dev` 启动开发服务，"
            "`npm run build` 构建生产文件。默认后端为 http://127.0.0.1:8000。\n"
        ).encode()
        notices = contents["THIRD_PARTY_NOTICES.md"].decode("utf-8")
        notices = notices.replace(
            "[`backend/app/evaluation/registry.json`](backend/app/evaluation/registry.json)",
            "研发/科研版中的 backend/app/evaluation/registry.json（本产品包不包含）",
        )
        contents["THIRD_PARTY_NOTICES.md"] = notices.encode("utf-8")
    version = tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    manifest = {
        "edition": edition,
        "label": label,
        "application_version": version,
        "kind": "source-only",
        "research_available": edition == "research",
        "contains_datasets": False,
        "contains_model_weights": False,
        "files": {
            name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())
        },
    }
    contents["edition-manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"agentic-{label}-{edition}-source.zip"
    if target.exists():
        raise FileExistsError(f"refusing to replace an existing archive: {target.name}")
    with ZipFile(target, "x", compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(contents.items()):
            item = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            item.compress_type = ZIP_DEFLATED
            archive.writestr(item, data)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=("product", "research", "both"), default="both")
    parser.add_argument("--label", default="v1.3.0-candidate")
    parser.add_argument("--output", type=Path, default=ROOT / "output/editions")
    args = parser.parse_args()
    selected = ("product", "research") if args.edition == "both" else (args.edition,)
    for edition in selected:
        result = build(ROOT, args.output, edition, args.label)
        print(
            json.dumps(
                {
                    "archive": str(result),
                    "bytes": result.stat().st_size,
                    "sha256": hashlib.sha256(result.read_bytes()).hexdigest(),
                }
            )
        )
