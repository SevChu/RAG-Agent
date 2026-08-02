from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from qdrant_client import QdrantClient, models

from app.ingestion.chunking import DocumentChunk
from app.knowledge.embedding import BGE_M3_DIMENSION
from app.knowledge.models import VectorPointSnapshot, VectorSearchResult

_POINT_NAMESPACE = UUID("ad388610-25a4-5c17-bdde-758af933bfe4")


class QdrantChunkStore:
    """Course-scoped access to one persistent Qdrant chunk collection."""

    def __init__(
        self,
        path: Path,
        *,
        collection_name: str = "knowledge_chunks_v1",
        vector_size: int = BGE_M3_DIMENSION,
        write_batch_size: int = 64,
        client: QdrantClient | None = None,
    ) -> None:
        if not collection_name.strip():
            raise ValueError("Qdrant collection name cannot be blank.")
        if vector_size < 1 or write_batch_size < 1:
            raise ValueError("Vector size and write batch size must be positive.")
        self.path = path.resolve()
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.write_batch_size = write_batch_size
        self._client = client or QdrantClient(path=str(self.path))

    def ensure_collection(self) -> None:
        if not self._client.collection_exists(self.collection_name):
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE,
                ),
                metadata={
                    "embedding_model": "BAAI/bge-m3",
                    "embedding_dimension": self.vector_size,
                    "isolation_key": "course_id",
                },
            )
            return
        info = self._client.get_collection(self.collection_name)
        vectors = info.config.params.vectors
        if not isinstance(vectors, models.VectorParams):
            raise RuntimeError("The existing Qdrant collection uses named vectors unexpectedly.")
        if vectors.size != self.vector_size or vectors.distance != models.Distance.COSINE:
            raise RuntimeError(
                "The existing Qdrant collection is incompatible with BGE-M3 "
                f"({vectors.size}, {vectors.distance})."
            )

    def replace_document(
        self,
        *,
        course_id: str,
        document_id: str,
        chunks: Sequence[DocumentChunk],
        vectors: Sequence[Sequence[float]],
    ) -> int:
        normalized_course = _required_identifier(course_id, "course_id")
        normalized_document = _required_identifier(document_id, "document_id")
        if not chunks or len(chunks) != len(vectors):
            raise ValueError("Chunks and vectors must be non-empty and have equal length.")
        self.ensure_collection()
        points = [
            self._point(
                course_id=normalized_course,
                document_id=normalized_document,
                chunk=chunk,
                vector=vector,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self.delete_document(
            course_id=normalized_course,
            document_id=normalized_document,
        )
        for start in range(0, len(points), self.write_batch_size):
            self._client.upsert(
                collection_name=self.collection_name,
                points=points[start : start + self.write_batch_size],
                wait=True,
            )
        return len(points)

    def search(
        self,
        *,
        course_id: str,
        vector: Sequence[float],
        limit: int = 10,
        document_ids: Sequence[str] | None = None,
    ) -> tuple[VectorSearchResult, ...]:
        normalized_course = _required_identifier(course_id, "course_id")
        checked_vector = self._checked_vector(vector)
        if limit < 1:
            raise ValueError("Search limit must be positive.")
        self.ensure_collection()
        conditions: list[models.Condition] = [
            models.FieldCondition(
                key="course_id",
                match=models.MatchValue(value=normalized_course),
            )
        ]
        if document_ids is not None:
            normalized_documents = [
                _required_identifier(value, "document_id") for value in document_ids
            ]
            if not normalized_documents:
                return ()
            conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=normalized_documents),
                )
            )
        response = self._client.query_points(
            collection_name=self.collection_name,
            query=checked_vector,
            query_filter=models.Filter(must=conditions),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return tuple(self._search_result(point) for point in response.points)

    def delete_document(self, *, course_id: str, document_id: str) -> None:
        normalized_course = _required_identifier(course_id, "course_id")
        normalized_document = _required_identifier(document_id, "document_id")
        self.ensure_collection()
        self._client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="course_id",
                            match=models.MatchValue(value=normalized_course),
                        ),
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=normalized_document),
                        ),
                    ]
                )
            ),
            wait=True,
        )

    def delete_course(self, *, course_id: str) -> None:
        normalized_course = _required_identifier(course_id, "course_id")
        self.ensure_collection()
        self._client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="course_id",
                            match=models.MatchValue(value=normalized_course),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def list_points(self, *, batch_size: int = 256) -> tuple[VectorPointSnapshot, ...]:
        """Return payload-only snapshots for consistency checks and acceptance reports."""

        if batch_size < 1:
            raise ValueError("batch_size must be positive.")
        if not self._client.collection_exists(self.collection_name):
            return ()
        snapshots: list[VectorPointSnapshot] = []
        offset: Any | None = None
        while True:
            records, offset = self._client.scroll(
                collection_name=self.collection_name,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            snapshots.extend(
                VectorPointSnapshot(
                    point_id=str(record.id),
                    payload=dict(record.payload or {}),
                )
                for record in records
            )
            if offset is None:
                break
        return tuple(snapshots)

    def close(self) -> None:
        self._client.close()

    def _point(
        self,
        *,
        course_id: str,
        document_id: str,
        chunk: DocumentChunk,
        vector: Sequence[float],
    ) -> models.PointStruct:
        if chunk.source.course_id != course_id or chunk.source.document_id != document_id:
            raise ValueError("Chunk source identifiers do not match the target course/document.")
        point_id = uuid5(
            _POINT_NAMESPACE,
            f"{course_id}:{document_id}:{chunk.chunk_index}",
        )
        payload: dict[str, Any] = {
            "course_id": course_id,
            "document_id": document_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "estimated_token_count": chunk.estimated_token_count,
            "overlap_token_count": chunk.overlap_token_count,
            "file_name": chunk.source.file_name,
            "file_type": chunk.source.file_type,
            "parser_name": chunk.source.parser_name,
            "section_path": list(chunk.source.section_path),
            "source_block_start": chunk.source.source_block_start,
            "source_block_end": chunk.source.source_block_end,
            "source_block_indices": list(chunk.source.source_block_indices),
            "context_block_indices": list(chunk.source.context_block_indices),
            "block_kinds": [kind.value for kind in chunk.source.block_kinds],
            "line_start": chunk.source.line_start,
            "line_end": chunk.source.line_end,
            "page_numbers": list(chunk.source.page_numbers),
            "slide_numbers": list(chunk.source.slide_numbers),
            "extraction_methods": [
                method.value for method in chunk.source.extraction_methods
            ],
            "minimum_ocr_confidence": chunk.source.minimum_ocr_confidence,
        }
        return models.PointStruct(
            id=point_id,
            vector=self._checked_vector(vector),
            payload=payload,
        )

    def _checked_vector(self, vector: Sequence[float]) -> list[float]:
        if len(vector) != self.vector_size:
            raise ValueError(
                f"Vector dimension must be {self.vector_size}, received {len(vector)}."
            )
        return [float(value) for value in vector]

    @staticmethod
    def _search_result(point: models.ScoredPoint) -> VectorSearchResult:
        payload = point.payload or {}
        return VectorSearchResult(
            point_id=str(point.id),
            score=float(point.score),
            course_id=str(payload["course_id"]),
            document_id=str(payload["document_id"]),
            chunk_index=int(payload["chunk_index"]),
            text=str(payload["text"]),
            payload=dict(payload),
        )


def _required_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be blank.")
    return normalized
