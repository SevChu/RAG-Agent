from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

import sklearn  # type: ignore[import-untyped]
import torch

from app.evaluation.benchmark import hash_file


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
