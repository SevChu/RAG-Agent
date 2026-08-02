from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.ingestion.chunking import ChunkingContext, StructuredDocumentChunker
from app.ingestion.models import BlockKind, ParsedBlock, ParsedDocument, SourceLocation
from app.knowledge import BGE_M3_DIMENSION, BgeM3Embedder, KnowledgeIndexer, QdrantChunkStore


class ConstantEmbeddingModel:
    def encode(self, inputs: list[str], **kwargs: Any) -> NDArray[np.float32]:
        vectors = np.zeros((len(inputs), BGE_M3_DIMENSION), dtype=np.float32)
        vectors[:, 0] = 1.0
        return vectors


def test_indexer_batches_chunks_and_searches_only_requested_course(tmp_path: Path) -> None:
    document = ParsedDocument(
        file_name="note.md",
        file_type="md",
        parser_name="test",
        blocks=(
            ParsedBlock(
                kind=BlockKind.PARAGRAPH,
                text="栈遵循后进先出。",
                source=SourceLocation(block_index=0, line_start=1, line_end=1),
            ),
            ParsedBlock(
                kind=BlockKind.PARAGRAPH,
                text="队列遵循先进先出。",
                source=SourceLocation(block_index=1, line_start=2, line_end=2),
            ),
        ),
    )
    chunking = StructuredDocumentChunker().chunk(
        document,
        context=ChunkingContext(course_id="course-a", document_id="document-a"),
    )
    model_path = tmp_path / "model"
    model_path.mkdir()
    embedder = BgeM3Embedder(
        model_path,
        device="cpu",
        model_factory=lambda path, device: ConstantEmbeddingModel(),
    )
    store = QdrantChunkStore(tmp_path / "qdrant")
    try:
        indexer = KnowledgeIndexer(embedder, store)

        result = indexer.index(
            chunking,
            course_id="course-a",
            document_id="document-a",
        )
        matches = indexer.search("什么是栈？", course_id="course-a")
        other_course = indexer.search("什么是栈？", course_id="course-b")

        assert result.chunk_count == len(chunking.chunks)
        assert result.vector_dimension == BGE_M3_DIMENSION
        assert result.device == "cpu"
        assert matches
        assert all(match.course_id == "course-a" for match in matches)
        assert other_course == ()
    finally:
        store.close()
