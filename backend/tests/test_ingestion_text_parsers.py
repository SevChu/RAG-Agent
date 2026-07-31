from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion import BlockKind, DocumentParserRegistry, build_default_registry
from app.ingestion.errors import (
    EmptyDocumentError,
    InvalidDocumentEncodingError,
    UnsupportedParserError,
)
from app.ingestion.parsers import MarkdownParser, PlainTextParser


def test_plain_text_parser_preserves_paragraph_order_and_line_locations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes(
        b"\xef\xbb\xbfFirst line\r\nsecond line\r\n\r\nThird paragraph\r\n"
    )

    result = PlainTextParser().parse(path, display_name="课程笔记.txt")

    assert result.file_name == "课程笔记.txt"
    assert result.file_type == "txt"
    assert result.parser_name == "plain-text-v1"
    assert [block.text for block in result.blocks] == [
        "First line\nsecond line",
        "Third paragraph",
    ]
    assert [block.kind for block in result.blocks] == [
        BlockKind.PARAGRAPH,
        BlockKind.PARAGRAPH,
    ]
    assert [
        (block.source.block_index, block.source.line_start, block.source.line_end)
        for block in result.blocks
    ] == [(0, 1, 2), (1, 4, 4)]
    assert result.character_count == len("First line\nsecond lineThird paragraph")


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b" \r\n\t\n",
    ],
)
def test_plain_text_parser_rejects_content_without_meaningful_text(
    tmp_path: Path,
    content: bytes,
) -> None:
    path = tmp_path / "blank.txt"
    path.write_bytes(content)

    with pytest.raises(EmptyDocumentError):
        PlainTextParser().parse(path)


@pytest.mark.parametrize("content", [b"\xff\xfeinvalid", b"valid\x00hidden"])
def test_text_parsers_reject_invalid_encoding(
    tmp_path: Path,
    content: bytes,
) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(content)

    with pytest.raises(InvalidDocumentEncodingError):
        PlainTextParser().parse(path)


def test_markdown_parser_preserves_structure_code_and_section_hierarchy(
    tmp_path: Path,
) -> None:
    path = tmp_path / "structured.md"
    path.write_text(
        "\n".join(
            [
                "# 数据结构",
                "",
                "课程简介。",
                "",
                "## 线性表",
                "",
                "- 顺序表",
                "- 链表",
                "",
                "| 操作 | 复杂度 |",
                "| --- | ---: |",
                "| 查找 | O(n) |",
                "",
                "```cpp",
                "int size = 0;",
                "```",
            ]
        ),
        encoding="utf-8",
    )

    result = MarkdownParser().parse(path)

    assert [block.kind for block in result.blocks] == [
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.HEADING,
        BlockKind.LIST,
        BlockKind.TABLE,
        BlockKind.CODE,
    ]
    assert result.blocks[0].section_path == ("数据结构",)
    assert result.blocks[1].section_path == ("数据结构",)
    assert result.blocks[2].section_path == ("数据结构", "线性表")
    assert result.blocks[-1].section_path == ("数据结构", "线性表")
    assert result.blocks[-1].language == "cpp"
    assert result.blocks[-1].text == "int size = 0;"
    assert (
        result.blocks[-1].source.line_start,
        result.blocks[-1].source.line_end,
    ) == (14, 16)
    assert result.warnings == ()


def test_markdown_parser_reports_unclosed_code_fence(tmp_path: Path) -> None:
    path = tmp_path / "unclosed.md"
    path.write_text("# 示例\n\n```python\nprint('ok')", encoding="utf-8")

    result = MarkdownParser().parse(path)

    assert result.blocks[-1].kind is BlockKind.CODE
    assert result.blocks[-1].language == "python"
    assert [warning.code for warning in result.warnings] == [
        "UNCLOSED_CODE_FENCE"
    ]


def test_markdown_parser_does_not_strip_meaningful_heading_hashes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "csharp.md"
    path.write_text("# C#\n\n## API ##", encoding="utf-8")

    result = MarkdownParser().parse(path)

    assert [block.text for block in result.blocks] == ["C#", "API"]


def test_default_registry_routes_case_insensitively_and_rejects_future_types(
    tmp_path: Path,
) -> None:
    text_path = tmp_path / "NOTES.TXT"
    text_path.write_text("content", encoding="utf-8")
    registry = build_default_registry()

    result = registry.parse(text_path)

    assert registry.supported_file_types == frozenset({"md", "txt"})
    assert result.file_type == "txt"
    with pytest.raises(UnsupportedParserError, match="pdf"):
        registry.parse(tmp_path / "future.pdf")


def test_registry_rejects_duplicate_file_type_registration() -> None:
    registry = DocumentParserRegistry((PlainTextParser(),))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(PlainTextParser())


def test_parsed_block_indexes_are_contiguous(tmp_path: Path) -> None:
    path = tmp_path / "outline.md"
    path.write_text("# A\n\nText\n\n## B\n\nMore", encoding="utf-8")

    result = MarkdownParser().parse(path)

    assert [block.source.block_index for block in result.blocks] == list(
        range(len(result.blocks))
    )
