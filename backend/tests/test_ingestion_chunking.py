from __future__ import annotations

import pytest

from app.ingestion import (
    BlockKind,
    ParsedBlock,
    ParsedDocument,
    SourceLocation,
)
from app.ingestion.chunking import (
    ChunkingConfig,
    ChunkingContext,
    EstimatedTokenCounter,
    StructuredDocumentChunker,
)
from app.ingestion.models import ExtractionMethod


def _block(
    index: int,
    kind: BlockKind,
    text: str,
    *,
    section_path: tuple[str, ...] = (),
    line: int | None = None,
    page: int | None = None,
    slide: int | None = None,
    extraction_method: ExtractionMethod | None = None,
) -> ParsedBlock:
    return ParsedBlock(
        kind=kind,
        text=text,
        source=SourceLocation(
            block_index=index,
            line_start=line,
            line_end=line,
            page_number=page,
            slide_number=slide,
            extraction_method=extraction_method,
        ),
        section_path=section_path,
    )


def _document(*blocks: ParsedBlock) -> ParsedDocument:
    return ParsedDocument(
        file_name="课程资料.md",
        file_type="md",
        parser_name="test-parser-v1",
        blocks=blocks,
    )


def test_chunker_keeps_sections_separate_and_repeats_heading_context() -> None:
    document = _document(
        _block(0, BlockKind.HEADING, "数据结构", section_path=("数据结构",), line=1),
        _block(1, BlockKind.PARAGRAPH, "课程简介", section_path=("数据结构",), line=2),
        _block(
            2,
            BlockKind.HEADING,
            "线性表",
            section_path=("数据结构", "线性表"),
            line=3,
        ),
        _block(
            3,
            BlockKind.PARAGRAPH,
            "顺序表和链表",
            section_path=("数据结构", "线性表"),
            line=4,
        ),
    )

    result = StructuredDocumentChunker().chunk(document)

    assert len(result.chunks) == 2
    assert result.chunks[0].text == "# 数据结构\n\n课程简介"
    assert result.chunks[1].text == "# 数据结构\n## 线性表\n\n顺序表和链表"
    assert result.chunks[0].source.source_block_indices == (0, 1)
    assert result.chunks[1].source.context_block_indices == (0, 2)
    assert result.chunks[1].source.source_block_indices == (0, 2, 3)
    assert result.chunks[1].source.line_start == 1
    assert result.chunks[1].source.line_end == 4


def test_chunker_keeps_lists_tables_and_code_intact_when_over_target() -> None:
    document = _document(
        _block(0, BlockKind.HEADING, "章节", section_path=("章节",)),
        _block(1, BlockKind.LIST, "列表项目甲乙丙丁", section_path=("章节",)),
        _block(2, BlockKind.TABLE, "字段甲 | 字段乙\n内容甲 | 内容乙", section_path=("章节",)),
        _block(3, BlockKind.CODE, "def answer():\n    return 42", section_path=("章节",)),
    )

    result = StructuredDocumentChunker().chunk(
        document,
        config=ChunkingConfig(target_tokens=8, overlap_tokens=2),
    )

    assert len(result.chunks) == 3
    assert "列表项目甲乙丙丁" in result.chunks[0].text
    assert result.chunks[0].source.block_kinds == (BlockKind.LIST,)
    assert result.chunks[0].source.source_block_indices == (0, 1)
    assert result.chunks[1].source.block_kinds == (BlockKind.TABLE,)
    assert result.chunks[2].source.block_kinds == (BlockKind.CODE,)
    assert [warning.code for warning in result.warnings] == [
        "PROTECTED_UNIT_OVER_TARGET",
        "PROTECTED_UNIT_OVER_TARGET",
        "PROTECTED_UNIT_OVER_TARGET",
    ]
    assert result.stats.protected_over_target_units == 3
    assert result.stats.over_target_chunks == 3


def test_chunker_splits_long_paragraph_with_configured_overlap() -> None:
    long_paragraph = "甲" * 50
    document = _document(
        _block(0, BlockKind.HEADING, "章节", section_path=("章节",)),
        _block(1, BlockKind.PARAGRAPH, long_paragraph, section_path=("章节",)),
    )

    result = StructuredDocumentChunker().chunk(
        document,
        config=ChunkingConfig(target_tokens=20, overlap_tokens=5),
    )

    assert len(result.chunks) > 1
    assert all(chunk.estimated_token_count <= 20 for chunk in result.chunks)
    assert result.chunks[0].overlap_token_count == 0
    assert all(chunk.overlap_token_count == 5 for chunk in result.chunks[1:])
    assert all(chunk.source.source_block_indices == (0, 1) for chunk in result.chunks)
    assert result.stats.chunks_with_overlap == len(result.chunks) - 1


def test_chunker_does_not_create_partial_overlap_for_ocr_paragraphs() -> None:
    document = _document(
        _block(
            0,
            BlockKind.PARAGRAPH,
            "第一段语义完整。",
            extraction_method=ExtractionMethod.OCR,
        ),
        _block(
            1,
            BlockKind.PARAGRAPH,
            "第二段语义完整。",
            extraction_method=ExtractionMethod.OCR,
        ),
    )

    result = StructuredDocumentChunker().chunk(
        document,
        config=ChunkingConfig(target_tokens=8, overlap_tokens=3),
    )

    assert [chunk.text for chunk in result.chunks] == [
        "第一段语义完整。",
        "第二段语义完整。",
    ]
    assert all(chunk.overlap_token_count == 0 for chunk in result.chunks)


def test_chunker_preserves_index_context_and_exact_source_locations() -> None:
    document = ParsedDocument(
        file_name="课件.pptx",
        file_type="pptx",
        parser_name="pptx-test-v1",
        blocks=(
            _block(0, BlockKind.PARAGRAPH, "甲" * 12, page=1, slide=2),
            _block(1, BlockKind.PARAGRAPH, "乙" * 12, page=2, slide=3),
        ),
    )

    result = StructuredDocumentChunker().chunk(
        document,
        config=ChunkingConfig(target_tokens=15, overlap_tokens=3),
        context=ChunkingContext(course_id="course-1", document_id="document-1"),
    )

    assert len(result.chunks) == 2
    second_source = result.chunks[1].source
    assert result.chunks[1].overlap_token_count == 3
    assert second_source.course_id == "course-1"
    assert second_source.document_id == "document-1"
    assert second_source.file_name == "课件.pptx"
    assert second_source.file_type == "pptx"
    assert second_source.parser_name == "pptx-test-v1"
    assert second_source.source_block_indices == (0, 1)
    assert second_source.page_numbers == (1, 2)
    assert second_source.slide_numbers == (2, 3)


def test_chunker_keeps_title_only_slides_and_reports_complete_coverage() -> None:
    document = ParsedDocument(
        file_name="封面课件.pptx",
        file_type="pptx",
        parser_name="pptx-test-v1",
        blocks=(
            _block(
                0,
                BlockKind.HEADING,
                "课程封面",
                section_path=("课程封面",),
                slide=1,
            ),
            _block(
                1,
                BlockKind.HEADING,
                "第一章",
                section_path=("第一章",),
                slide=2,
            ),
            _block(
                2,
                BlockKind.PARAGRAPH,
                "章节正文",
                section_path=("第一章",),
                slide=2,
            ),
            _block(
                3,
                BlockKind.HEADING,
                "第一章",
                section_path=("第一章",),
                slide=3,
            ),
            _block(
                4,
                BlockKind.PARAGRAPH,
                "重复标题下的新一页",
                section_path=("第一章",),
                slide=3,
            ),
        ),
    )

    result = StructuredDocumentChunker().chunk(document)

    assert [chunk.text for chunk in result.chunks] == [
        "# 课程封面",
        "# 第一章\n\n章节正文",
        "# 第一章\n\n重复标题下的新一页",
    ]
    assert result.chunks[1].source.context_block_indices == (1,)
    assert result.chunks[2].source.context_block_indices == (3,)
    assert result.stats.covered_source_blocks == 5
    assert result.stats.uncovered_source_blocks == 0


def test_chunking_stats_report_lengths_counts_and_anomalies() -> None:
    document = _document(
        _block(0, BlockKind.PARAGRAPH, "甲" * 10),
        _block(1, BlockKind.PARAGRAPH, "乙" * 10),
    )

    result = StructuredDocumentChunker().chunk(
        document,
        config=ChunkingConfig(target_tokens=12, overlap_tokens=2),
    )

    assert result.stats.source_block_count == 2
    assert result.stats.covered_source_blocks == 2
    assert result.stats.uncovered_source_blocks == 0
    assert result.stats.chunk_count == 2
    assert result.stats.min_estimated_tokens == 10
    assert result.stats.max_estimated_tokens == 12
    assert result.stats.average_estimated_tokens == 11.0
    assert result.stats.average_overlap_tokens == 1.0
    assert result.stats.anomaly_count == 0


@pytest.mark.parametrize(
    ("target", "overlap"),
    [(0, 0), (10, -1), (10, 10), (10, 11)],
)
def test_chunking_config_rejects_invalid_sizes(target: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(target_tokens=target, overlap_tokens=overlap)


def test_estimated_token_counter_is_deterministic_for_chinese_and_english() -> None:
    counter = EstimatedTokenCounter()

    assert counter.count("数据 structure123") == 5
    assert counter.suffix("甲乙丙丁", 2) == "丙丁"


def test_token_split_prefers_sentence_boundaries_and_sentence_overlap() -> None:
    counter = EstimatedTokenCounter()
    text = (
        "Alpha beta gamma delta. "
        "Second sentence stays complete. "
        "Third sentence also stays complete."
    )

    segments = counter.split(text, max_tokens=12, overlap_tokens=5)

    assert len(segments) >= 2
    assert all(segment.endswith(".") for segment, _ in segments)
    assert segments[1][0].startswith("Second sentence")


def test_chunk_overlap_drops_partial_sentence_when_budget_is_too_small() -> None:
    document = _document(
        _block(
            0,
            BlockKind.PARAGRAPH,
            "First sentence ends here.",
        ),
        _block(1, BlockKind.PARAGRAPH, "A new paragraph starts cleanly."),
    )

    result = StructuredDocumentChunker().chunk(
        document,
        config=ChunkingConfig(target_tokens=14, overlap_tokens=3),
    )

    assert result.chunks[-1].text.startswith("A new paragraph")
    assert result.chunks[-1].overlap_token_count == 0
