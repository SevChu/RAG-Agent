from __future__ import annotations

from collections.abc import Sequence

from app.knowledge import EmbeddingBatch, VectorSearchResult
from app.retrieval import DenseRetriever


class RecordingEmbedder:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        self.inputs = list(texts)
        return EmbeddingBatch(
            vectors=((1.0, 0.0),),
            device="cpu",
            fallback_reason="test fallback",
        )


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def search(
        self,
        *,
        course_id: str,
        vector: Sequence[float],
        limit: int = 10,
        document_ids: Sequence[str] | None = None,
    ) -> tuple[VectorSearchResult, ...]:
        self.calls.append(
            {
                "course_id": course_id,
                "vector": tuple(vector),
                "limit": limit,
                "document_ids": tuple(document_ids or ()),
            }
        )
        return (
            VectorSearchResult(
                point_id="point-1",
                score=0.91,
                course_id=course_id,
                document_id="document-1",
                chunk_index=2,
                text="栈遵循后进先出原则。",
                payload={"file_name": "栈.md"},
            ),
        )


def test_dense_retriever_normalizes_query_and_preserves_scope() -> None:
    embedder = RecordingEmbedder()
    store = RecordingStore()
    retriever = DenseRetriever(embedder, store)

    result = retriever.search(
        course_id="course-a",
        query="  什么是栈？  ",
        top_k=5,
        document_ids=["document-1"],
    )

    assert result.query == "什么是栈？"
    assert result.embedding_device == "cpu"
    assert result.fallback_reason == "test fallback"
    assert [hit.text for hit in result.hits] == ["栈遵循后进先出原则。"]
    assert embedder.inputs == ["什么是栈？"]
    assert store.calls == [
        {
            "course_id": "course-a",
            "vector": (1.0, 0.0),
            "limit": 5,
            "document_ids": ("document-1",),
        }
    ]


def test_dense_retriever_skips_model_when_scope_has_no_ready_documents() -> None:
    embedder = RecordingEmbedder()
    store = RecordingStore()

    result = DenseRetriever(embedder, store).search(
        course_id="course-a",
        query="什么是队列？",
        document_ids=[],
    )

    assert result.hits == ()
    assert result.embedding_device is None
    assert embedder.inputs == []
    assert store.calls == []
