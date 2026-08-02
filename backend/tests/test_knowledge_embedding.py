from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.knowledge import BGE_M3_DIMENSION, BgeM3Embedder, EmbeddingDevice


class FakeEmbeddingModel:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def encode(self, inputs: list[str], **kwargs: Any) -> NDArray[np.float32]:
        if self.fail:
            raise RuntimeError("simulated CUDA out of memory")
        vectors = np.zeros((len(inputs), BGE_M3_DIMENSION), dtype=np.float32)
        vectors[:, 0] = 1.0
        return vectors


def test_embedder_uses_cuda_when_available(tmp_path: Path) -> None:
    devices: list[str] = []

    def factory(path: Path, device: str) -> FakeEmbeddingModel:
        assert path == tmp_path.resolve()
        devices.append(device)
        return FakeEmbeddingModel()

    embedder = BgeM3Embedder(
        tmp_path,
        model_factory=factory,
        cuda_available=lambda: True,
    )

    batch = embedder.embed(["第一段", "second chunk"])

    assert devices == [EmbeddingDevice.CUDA]
    assert batch.device == EmbeddingDevice.CUDA
    assert batch.fallback_reason is None
    assert len(batch.vectors) == 2
    assert len(batch.vectors[0]) == BGE_M3_DIMENSION


def test_embedder_falls_back_to_cpu_after_cuda_runtime_failure(tmp_path: Path) -> None:
    devices: list[str] = []

    def factory(path: Path, device: str) -> FakeEmbeddingModel:
        devices.append(device)
        return FakeEmbeddingModel(fail=device == EmbeddingDevice.CUDA)

    embedder = BgeM3Embedder(
        tmp_path,
        device=EmbeddingDevice.CUDA,
        model_factory=factory,
        cuda_available=lambda: True,
    )

    batch = embedder.embed(["触发回退"])

    assert devices == [EmbeddingDevice.CUDA, EmbeddingDevice.CPU]
    assert batch.device == EmbeddingDevice.CPU
    assert batch.fallback_reason is not None
    assert "simulated CUDA out of memory" in batch.fallback_reason


def test_embedder_uses_cpu_when_cuda_is_unavailable(tmp_path: Path) -> None:
    embedder = BgeM3Embedder(
        tmp_path,
        model_factory=lambda path, device: FakeEmbeddingModel(),
        cuda_available=lambda: False,
    )

    batch = embedder.embed(["CPU fallback"])

    assert batch.device == EmbeddingDevice.CPU
    assert batch.fallback_reason is not None


def test_embedder_rejects_blank_input(tmp_path: Path) -> None:
    embedder = BgeM3Embedder(
        tmp_path,
        model_factory=lambda path, device: FakeEmbeddingModel(),
        cuda_available=lambda: False,
    )

    try:
        embedder.embed(["  "])
    except ValueError as error:
        assert "non-blank" in str(error)
    else:
        raise AssertionError("Blank embedding input should fail.")
