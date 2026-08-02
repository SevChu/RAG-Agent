from pathlib import Path

import pytest

from app.ingestion.chunking import ChunkSourceMetadata, DocumentChunk
from app.ingestion.models import BlockKind
from app.knowledge import BGE_M3_DIMENSION, QdrantChunkStore


def _chunk(*, course_id: str, document_id: str, index: int, text: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_index=index,
        text=text,
        estimated_token_count=10,
        overlap_token_count=0,
        source=ChunkSourceMetadata(
            course_id=course_id,
            document_id=document_id,
            file_name="note.md",
            file_type="md",
            parser_name="test",
            section_path=("测试章节",),
            source_block_start=index,
            source_block_end=index,
            source_block_indices=(index,),
            context_block_indices=(),
            block_kinds=(BlockKind.PARAGRAPH,),
            line_start=index + 1,
            line_end=index + 1,
            page_numbers=(),
            slide_numbers=(),
            extraction_methods=(),
            minimum_ocr_confidence=None,
        ),
    )


def _vector(position: int = 0) -> list[float]:
    vector = [0.0] * BGE_M3_DIMENSION
    vector[position] = 1.0
    return vector


def test_store_creates_bge_collection_and_isolates_courses(tmp_path: Path) -> None:
    store = QdrantChunkStore(tmp_path / "qdrant")
    try:
        store.replace_document(
            course_id="course-a",
            document_id="shared-document",
            chunks=[
                _chunk(
                    course_id="course-a",
                    document_id="shared-document",
                    index=0,
                    text="课程 A 的栈",
                )
            ],
            vectors=[_vector()],
        )
        store.replace_document(
            course_id="course-b",
            document_id="shared-document",
            chunks=[
                _chunk(
                    course_id="course-b",
                    document_id="shared-document",
                    index=0,
                    text="课程 B 的栈",
                )
            ],
            vectors=[_vector()],
        )

        course_a = store.search(course_id="course-a", vector=_vector())
        course_b = store.search(course_id="course-b", vector=_vector())

        assert [result.text for result in course_a] == ["课程 A 的栈"]
        assert [result.text for result in course_b] == ["课程 B 的栈"]
        assert all(result.course_id == "course-a" for result in course_a)
        assert all(result.course_id == "course-b" for result in course_b)
    finally:
        store.close()

def test_replace_document_removes_stale_chunks_only_in_target_course(
    tmp_path: Path,
) -> None:
    store = QdrantChunkStore(tmp_path / "qdrant", write_batch_size=1)
    try:
        store.replace_document(
            course_id="course-a",
            document_id="document-1",
            chunks=[
                _chunk(course_id="course-a", document_id="document-1", index=0, text="旧一"),
                _chunk(course_id="course-a", document_id="document-1", index=1, text="旧二"),
            ],
            vectors=[_vector(), _vector()],
        )
        store.replace_document(
            course_id="course-b",
            document_id="document-1",
            chunks=[
                _chunk(course_id="course-b", document_id="document-1", index=0, text="保留")
            ],
            vectors=[_vector()],
        )

        store.replace_document(
            course_id="course-a",
            document_id="document-1",
            chunks=[
                _chunk(course_id="course-a", document_id="document-1", index=0, text="新内容")
            ],
            vectors=[_vector()],
        )

        assert [item.text for item in store.search(course_id="course-a", vector=_vector())] == [
            "新内容"
        ]
        assert [item.text for item in store.search(course_id="course-b", vector=_vector())] == [
            "保留"
        ]
    finally:
        store.close()


def test_store_rejects_cross_course_chunk_metadata_before_replacement(
    tmp_path: Path,
) -> None:
    store = QdrantChunkStore(tmp_path / "qdrant")
    try:
        valid = _chunk(
            course_id="course-a",
            document_id="document-1",
            index=0,
            text="原内容",
        )
        store.replace_document(
            course_id="course-a",
            document_id="document-1",
            chunks=[valid],
            vectors=[_vector()],
        )

        with pytest.raises(ValueError, match="do not match"):
            store.replace_document(
                course_id="course-a",
                document_id="document-1",
                chunks=[
                    _chunk(
                        course_id="course-b",
                        document_id="document-1",
                        index=0,
                        text="越权内容",
                    )
                ],
                vectors=[_vector()],
            )

        assert [item.text for item in store.search(course_id="course-a", vector=_vector())] == [
            "原内容"
        ]
    finally:
        store.close()


def test_store_rejects_wrong_vector_dimension(tmp_path: Path) -> None:
    store = QdrantChunkStore(tmp_path / "qdrant")
    try:
        with pytest.raises(ValueError, match="Vector dimension"):
            store.replace_document(
                course_id="course-a",
                document_id="document-1",
                chunks=[
                    _chunk(
                        course_id="course-a",
                        document_id="document-1",
                        index=0,
                        text="错误维度",
                    )
                ],
                vectors=[[1.0, 0.0]],
            )
    finally:
        store.close()
