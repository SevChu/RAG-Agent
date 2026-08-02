from pathlib import Path
from uuid import UUID

from app.knowledge.audit import KnowledgeBaseAuditor, render_markdown
from app.knowledge.models import VectorPointSnapshot
from app.models import Course, Document, DocumentStatus


def _document(
    *,
    course_id: UUID,
    document_id: UUID,
    status: DocumentStatus = DocumentStatus.COMPLETED,
) -> Document:
    return Document(
        id=document_id,
        course_id=course_id,
        original_name="课件.pptx",
        stored_name=f"{document_id}.pptx",
        file_type="pptx",
        file_size=4,
        sha256="a" * 64,
        status=status,
        error_message="可读原因" if status is DocumentStatus.FAILED else None,
    )


def _point(*, course_id: UUID, document_id: UUID, index: int) -> VectorPointSnapshot:
    return VectorPointSnapshot(
        point_id=f"point-{index}",
        payload={
            "course_id": str(course_id),
            "document_id": str(document_id),
            "chunk_index": index,
            "text": f"第 {index + 1} 个完整知识片段",
            "estimated_token_count": 12,
            "overlap_token_count": 0,
            "file_name": "课件.pptx",
            "file_type": "pptx",
            "parser_name": "test",
            "section_path": ["第三章", "栈"],
            "source_block_start": index,
            "source_block_end": index,
            "source_block_indices": [index],
            "context_block_indices": [],
            "block_kinds": ["paragraph"],
            "line_start": None,
            "line_end": None,
            "page_numbers": [],
            "slide_numbers": [index + 1],
            "extraction_methods": [],
            "minimum_ocr_confidence": None,
        },
    )


def test_audit_accepts_consistent_completed_document(tmp_path: Path) -> None:
    course = Course(id=UUID(int=1), name="数据结构")
    document = _document(course_id=course.id, document_id=UUID(int=2))
    source = tmp_path / str(course.id) / document.stored_name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pptx")

    report = KnowledgeBaseAuditor(tmp_path).audit(
        courses=[course],
        documents=[document],
        points=(
            _point(course_id=course.id, document_id=document.id, index=0),
            _point(course_id=course.id, document_id=document.id, index=1),
        ),
    )

    assert report.passed
    assert report.errors == ()
    assert report.documents[0].point_count == 2
    assert report.documents[0].slide_numbers == (1, 2)
    assert "第三章 / 栈" in render_markdown(report)


def test_audit_detects_orphans_missing_file_and_broken_chunks(tmp_path: Path) -> None:
    course = Course(id=UUID(int=10), name="数据结构")
    document = _document(course_id=course.id, document_id=UUID(int=20))
    orphan = tmp_path / str(course.id) / "orphan.txt"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("orphan", encoding="utf-8")
    orphan_vector = _point(course_id=course.id, document_id=UUID(int=99), index=0)
    broken = _point(course_id=course.id, document_id=document.id, index=2)

    report = KnowledgeBaseAuditor(tmp_path).audit(
        courses=[course],
        documents=[document],
        points=(broken, orphan_vector),
    )

    codes = {issue.code for issue in report.errors}
    assert not report.passed
    assert {
        "MISSING_SOURCE_FILE",
        "NON_CONTIGUOUS_CHUNKS",
        "ORPHAN_VECTOR",
        "ORPHAN_UPLOAD_FILE",
    } <= codes


def test_audit_requires_complete_vector_source_metadata(tmp_path: Path) -> None:
    course = Course(id=UUID(int=100), name="数据结构")
    document = _document(course_id=course.id, document_id=UUID(int=200))
    source = tmp_path / str(course.id) / document.stored_name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pptx")
    point = _point(course_id=course.id, document_id=document.id, index=0)
    point.payload.pop("context_block_indices")

    report = KnowledgeBaseAuditor(tmp_path).audit(
        courses=[course],
        documents=[document],
        points=(point,),
    )

    assert "INCOMPLETE_VECTOR_METADATA" in {issue.code for issue in report.errors}


def test_structure_report_samples_start_middle_and_end(tmp_path: Path) -> None:
    course = Course(id=UUID(int=300), name="数据结构")
    document = _document(course_id=course.id, document_id=UUID(int=400))
    source = tmp_path / str(course.id) / document.stored_name
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pptx")

    report = KnowledgeBaseAuditor(tmp_path, sample_chunks=3).audit(
        courses=[course],
        documents=[document],
        points=tuple(
            _point(course_id=course.id, document_id=document.id, index=index)
            for index in range(5)
        ),
    )

    assert [sample.chunk_index for sample in report.documents[0].samples] == [0, 2, 4]
