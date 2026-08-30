from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import torch
from sentence_transformers import CrossEncoder

from app.knowledge.evidence import ContentRole, assess_evidence
from app.knowledge.models import EmbeddingDevice, VectorSearchResult
from app.retrieval.models import DenseRetrievalResult, RerankedRetrievalResult


class CrossEncoderModel(Protocol):
    def predict(self, inputs: list[tuple[str, str]], **kwargs: Any) -> Any: ...


ModelFactory = Callable[[Path, str, int], CrossEncoderModel]

_TERM_ALIASES = (
    ("二分查找", "折半查找"),
    ("哈希", "散列"),
    ("Dijkstra", "迪杰斯特拉"),
)
_CONCEPT_GROUPS = _TERM_ALIASES + (
    ("邻接矩阵",),
    ("邻接表",),
    ("栈",),
    ("队列",),
    ("红黑树",),
    ("TCP",),
)


def expand_query_terms(query: str) -> str:
    """Add a small audited synonym set without asking an LLM to rewrite the query."""

    aliases: list[str] = []
    lowered_query = query.lower()
    for left, right in _TERM_ALIASES:
        lowered_left = left.lower()
        lowered_right = right.lower()
        if lowered_left in lowered_query and lowered_right not in lowered_query:
            aliases.append(right)
        elif lowered_right in lowered_query and lowered_left not in lowered_query:
            aliases.append(left)
    if not aliases:
        return query
    return f"{query}\n相关术语：{'、'.join(aliases)}"


def matches_query_concepts(query: str, passage: str) -> bool:
    """Require an explicitly named audited concept to appear in the passage."""

    lowered_query = query.lower()
    lowered_passage = passage.lower()
    requested_groups = [
        group for group in _CONCEPT_GROUPS if any(term.lower() in lowered_query for term in group)
    ]
    if not requested_groups:
        return True
    return any(any(term.lower() in lowered_passage for term in group) for group in requested_groups)


class BgeReranker:
    """Local-only BGE cross-encoder with evidence-role gating and CUDA fallback."""

    def __init__(
        self,
        model_path: Path,
        *,
        device: EmbeddingDevice | str = EmbeddingDevice.AUTO,
        batch_size: int = 4,
        max_length: int = 512,
        model_factory: ModelFactory | None = None,
        cuda_available: Callable[[], bool] | None = None,
    ) -> None:
        self.model_path = model_path.resolve()
        self.device_preference = EmbeddingDevice(device)
        if batch_size < 1:
            raise ValueError("Reranker batch size must be positive.")
        if max_length < 32:
            raise ValueError("Reranker maximum length must be at least 32 tokens.")
        self.batch_size = batch_size
        self.max_length = max_length
        self._model_factory = model_factory or _load_cross_encoder
        self._cuda_available = cuda_available or torch.cuda.is_available
        self._model: CrossEncoderModel | None = None
        self._device, self._fallback_reason = self._select_initial_device()

    @property
    def active_device(self) -> str:
        return self._device

    def rerank(
        self,
        dense: DenseRetrievalResult,
        *,
        top_k: int,
        allow_exercise_questions: bool = False,
    ) -> RerankedRetrievalResult:
        if top_k < 1:
            raise ValueError("Reranker top_k must be positive.")
        if not dense.hits:
            return RerankedRetrievalResult(
                query=dense.query,
                hits=(),
                dense_candidate_count=0,
                rejected_evidence_count=0,
                embedding_device=dense.embedding_device,
                reranker_device=None,
                fallback_reason=dense.fallback_reason,
            )

        scores = self.score_passages(dense.query, [hit.text for hit in dense.hits])
        ranked: list[VectorSearchResult] = []
        rejected = 0
        for hit, score in zip(dense.hits, scores, strict=True):
            assessment = assess_evidence(hit)
            concept_matched = matches_query_concepts(dense.query, hit.text)
            role_allowed = assessment.eligible or (
                allow_exercise_questions and assessment.role is ContentRole.EXERCISE_QUESTION
            )
            eligible = role_allowed and concept_matched
            rejection_reason = assessment.reason
            if role_allowed and not concept_matched:
                rejection_reason = "片段未出现问题中明确指定的核心概念。"
            elif role_allowed:
                rejection_reason = None
            metadata = dict(hit.payload)
            metadata.update(
                {
                    "dense_score": hit.score,
                    "reranker_score": score,
                    "content_role": assessment.role.value,
                    "evidence_eligible": eligible,
                    "evidence_rejection_reason": rejection_reason,
                }
            )
            reranked_hit = VectorSearchResult(
                point_id=hit.point_id,
                score=score,
                course_id=hit.course_id,
                document_id=hit.document_id,
                chunk_index=hit.chunk_index,
                text=hit.text,
                payload=metadata,
            )
            if eligible:
                ranked.append(reranked_hit)
            else:
                rejected += 1

        ranked.sort(key=lambda item: item.score, reverse=True)
        fallback_reasons = [
            reason for reason in (dense.fallback_reason, self._fallback_reason) if reason
        ]
        return RerankedRetrievalResult(
            query=dense.query,
            hits=tuple(ranked[:top_k]),
            dense_candidate_count=len(dense.hits),
            rejected_evidence_count=rejected,
            embedding_device=dense.embedding_device,
            reranker_device=self._device,
            fallback_reason=" ".join(fallback_reasons) or None,
        )

    def score_passages(
        self,
        query: str,
        passages: Sequence[str],
    ) -> tuple[float, ...]:
        """Score passages without applying product-specific evidence gates."""

        if not query.strip():
            raise ValueError("Reranker query cannot be blank.")
        if not passages:
            return ()
        try:
            raw_scores = self._run_model(query, passages)
        except RuntimeError as error:
            if self._device != EmbeddingDevice.CUDA:
                raise
            self._fallback_to_cpu(error)
            raw_scores = self._run_model(query, passages)
        clipped = np.clip(raw_scores, -50.0, 50.0)
        normalized = 1.0 / (1.0 + np.exp(-clipped))
        return tuple(float(value) for value in normalized)

    def _run_model(
        self,
        query: str,
        passages: Sequence[str],
    ) -> np.ndarray[Any, np.dtype[np.float64]]:
        expanded_query = expand_query_terms(query)
        pairs = [(expanded_query, passage) for passage in passages]
        output = self._get_model().predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            activation_fn=torch.nn.Identity(),
            convert_to_numpy=True,
        )
        scores = np.asarray(output, dtype=np.float64).reshape(-1)
        if scores.shape != (len(passages),):
            raise RuntimeError(f"Reranker returned {scores.shape}; expected {(len(passages),)}.")
        return scores

    def _get_model(self) -> CrossEncoderModel:
        if self._model is None:
            if not self.model_path.is_dir():
                raise FileNotFoundError(
                    f"Local reranker model directory does not exist: {self.model_path}"
                )
            self._model = self._model_factory(
                self.model_path,
                self._device,
                self.max_length,
            )
        return self._model

    def _select_initial_device(self) -> tuple[str, str | None]:
        if self.device_preference is EmbeddingDevice.CPU:
            return EmbeddingDevice.CPU, None
        if self._cuda_available():
            return EmbeddingDevice.CUDA, None
        return (
            EmbeddingDevice.CPU,
            "CUDA was requested or preferred for reranking but is unavailable; using CPU.",
        )

    def _fallback_to_cpu(self, error: RuntimeError) -> None:
        self._model = None
        self._device = EmbeddingDevice.CPU
        self._fallback_reason = f"CUDA reranking failed; using CPU: {error}"
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _load_cross_encoder(
    model_path: Path,
    device: str,
    max_length: int,
) -> CrossEncoderModel:
    model_kwargs: dict[str, Any] | None = None
    if device == EmbeddingDevice.CUDA:
        model_kwargs = {"torch_dtype": torch.float16}
    model = CrossEncoder(
        str(model_path),
        device=device,
        max_length=max_length,
        local_files_only=True,
        trust_remote_code=False,
        model_kwargs=model_kwargs,
    )
    return cast(CrossEncoderModel, model)
