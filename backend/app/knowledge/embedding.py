from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import torch
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

from app.knowledge.models import EmbeddingBatch, EmbeddingDevice

BGE_M3_DIMENSION = 1024


class EmbeddingModel(Protocol):
    def encode(self, inputs: list[str], **kwargs: Any) -> NDArray[np.float32]: ...


ModelFactory = Callable[[Path, str], EmbeddingModel]


class BgeM3Embedder:
    """Local-only BGE-M3 dense embedding with transparent CUDA fallback."""

    def __init__(
        self,
        model_path: Path,
        *,
        device: EmbeddingDevice | str = EmbeddingDevice.AUTO,
        batch_size: int = 8,
        model_factory: ModelFactory | None = None,
        cuda_available: Callable[[], bool] | None = None,
    ) -> None:
        self.model_path = model_path.resolve()
        self.device_preference = EmbeddingDevice(device)
        if batch_size < 1:
            raise ValueError("Embedding batch size must be positive.")
        self.batch_size = batch_size
        self._model_factory = model_factory or _load_sentence_transformer
        self._cuda_available = cuda_available or torch.cuda.is_available
        self._model: EmbeddingModel | None = None
        self._device, self._fallback_reason = self._select_initial_device()

    @property
    def dimension(self) -> int:
        return BGE_M3_DIMENSION

    @property
    def active_device(self) -> str:
        return self._device

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        normalized = [text.strip() for text in texts]
        if not normalized or any(not text for text in normalized):
            raise ValueError("Embedding input must contain non-blank text.")
        try:
            vectors = self._encode(normalized)
        except RuntimeError as error:
            if self._device != EmbeddingDevice.CUDA:
                raise
            self._fallback_to_cpu(error)
            vectors = self._encode(normalized)
        return EmbeddingBatch(
            vectors=tuple(tuple(float(value) for value in row) for row in vectors),
            device=self._device,
            fallback_reason=self._fallback_reason,
        )

    def _encode(self, texts: list[str]) -> NDArray[np.float32]:
        model = self._get_model()
        output = model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        vectors = np.asarray(output, dtype=np.float32)
        if vectors.shape != (len(texts), self.dimension):
            raise RuntimeError(
                "BGE-M3 returned an unexpected vector shape: "
                f"{vectors.shape}; expected {(len(texts), self.dimension)}."
            )
        return vectors

    def _get_model(self) -> EmbeddingModel:
        if self._model is None:
            if not self.model_path.is_dir():
                raise FileNotFoundError(
                    f"Local BGE-M3 model directory does not exist: {self.model_path}"
                )
            self._model = self._model_factory(self.model_path, self._device)
        return self._model

    def _select_initial_device(self) -> tuple[str, str | None]:
        if self.device_preference is EmbeddingDevice.CPU:
            return EmbeddingDevice.CPU, None
        if self._cuda_available():
            return EmbeddingDevice.CUDA, None
        return (
            EmbeddingDevice.CPU,
            "CUDA was requested or preferred but is unavailable; using CPU.",
        )

    def _fallback_to_cpu(self, error: RuntimeError) -> None:
        self._model = None
        self._device = EmbeddingDevice.CPU
        self._fallback_reason = f"CUDA inference failed; using CPU: {error}"
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _load_sentence_transformer(model_path: Path, device: str) -> EmbeddingModel:
    model_kwargs: dict[str, Any] | None = None
    if device == EmbeddingDevice.CUDA:
        model_kwargs = {"torch_dtype": torch.float16}
    model = SentenceTransformer(
        str(model_path),
        device=device,
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs=model_kwargs,
    )
    return cast(EmbeddingModel, model)
