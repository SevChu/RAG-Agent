from __future__ import annotations

import re
from pathlib import Path

from app.ingestion.errors import EmptyDocumentError
from app.ingestion.models import (
    BlockKind,
    ParsedBlock,
    ParsedDocument,
    ParseWarning,
    SourceLocation,
)
from app.ingestion.parsers.base import ParseProgressCallback
from app.ingestion.parsers.text import read_utf8_text

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*([^\s`]*)?.*$")
LIST_RE = re.compile(r"^[ \t]*(?:[-+*]|\d+[.)])[ \t]+")
TABLE_DELIMITER_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$"
)


class MarkdownParser:
    file_types = frozenset({"md"})
    parser_name = "markdown-structured-v1"

    def parse(
        self,
        path: Path,
        *,
        display_name: str | None = None,
        progress_callback: ParseProgressCallback | None = None,
    ) -> ParsedDocument:
        lines = read_utf8_text(path).split("\n")
        blocks: list[ParsedBlock] = []
        warnings: list[ParseWarning] = []
        section_levels: list[tuple[int, str]] = []
        index = 0

        def section_path() -> tuple[str, ...]:
            return tuple(title for _, title in section_levels)

        def append_block(
            kind: BlockKind,
            text: str,
            line_start: int,
            line_end: int,
            *,
            language: str | None = None,
        ) -> None:
            cleaned = text.strip("\n")
            if not cleaned.strip():
                return
            blocks.append(
                ParsedBlock(
                    kind=kind,
                    text=cleaned,
                    source=SourceLocation(
                        block_index=len(blocks),
                        line_start=line_start,
                        line_end=line_end,
                    ),
                    section_path=section_path(),
                    language=language,
                )
            )

        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue

            heading_match = HEADING_RE.match(line)
            if heading_match:
                level = len(heading_match.group(1))
                title = re.sub(
                    r"[ \t]+#+[ \t]*$",
                    "",
                    heading_match.group(2).strip(),
                )
                section_levels = [
                    item for item in section_levels if item[0] < level
                ]
                section_levels.append((level, title))
                append_block(
                    BlockKind.HEADING,
                    title,
                    index + 1,
                    index + 1,
                )
                index += 1
                continue

            fence_match = FENCE_RE.match(line)
            if fence_match:
                fence = fence_match.group(1)
                language = fence_match.group(2) or None
                start = index
                index += 1
                code_lines: list[str] = []
                closed = False
                while index < len(lines):
                    candidate = lines[index]
                    stripped_candidate = candidate.strip()
                    if (
                        stripped_candidate
                        and set(stripped_candidate) == {fence[0]}
                        and len(stripped_candidate) >= len(fence)
                    ):
                        closed = True
                        break
                    code_lines.append(candidate)
                    index += 1
                end = index + 1 if closed else len(lines)
                append_block(
                    BlockKind.CODE,
                    "\n".join(code_lines),
                    start + 1,
                    end,
                    language=language,
                )
                if not closed:
                    warnings.append(
                        ParseWarning(
                            code="UNCLOSED_CODE_FENCE",
                            message="A fenced code block reaches the end of the document.",
                            line_start=start + 1,
                            line_end=len(lines),
                        )
                    )
                else:
                    index += 1
                continue

            if self._is_table_start(lines, index):
                start = index
                table_lines = [line.rstrip()]
                index += 1
                while index < len(lines) and "|" in lines[index] and lines[index].strip():
                    table_lines.append(lines[index].rstrip())
                    index += 1
                append_block(
                    BlockKind.TABLE,
                    "\n".join(table_lines),
                    start + 1,
                    index,
                )
                continue

            if LIST_RE.match(line):
                start = index
                list_lines = [line.rstrip()]
                index += 1
                while index < len(lines):
                    candidate = lines[index]
                    if not candidate.strip():
                        break
                    if LIST_RE.match(candidate) or candidate.startswith((" ", "\t")):
                        list_lines.append(candidate.rstrip())
                        index += 1
                        continue
                    break
                append_block(
                    BlockKind.LIST,
                    "\n".join(list_lines),
                    start + 1,
                    index,
                )
                continue

            start = index
            paragraph_lines = [line.rstrip()]
            index += 1
            while index < len(lines) and lines[index].strip():
                if (
                    HEADING_RE.match(lines[index])
                    or FENCE_RE.match(lines[index])
                    or LIST_RE.match(lines[index])
                    or self._is_table_start(lines, index)
                ):
                    break
                paragraph_lines.append(lines[index].rstrip())
                index += 1
            append_block(
                BlockKind.PARAGRAPH,
                "\n".join(paragraph_lines),
                start + 1,
                index,
            )

        if not blocks:
            raise EmptyDocumentError(
                "The Markdown document contains no meaningful content."
            )
        if progress_callback is not None:
            progress_callback(len(lines), len(lines), f"已解析 {len(lines)} 行文本")
        return ParsedDocument(
            file_name=display_name or path.name,
            file_type="md",
            parser_name=self.parser_name,
            blocks=tuple(blocks),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _is_table_start(lines: list[str], index: int) -> bool:
        return (
            index + 1 < len(lines)
            and "|" in lines[index]
            and TABLE_DELIMITER_RE.match(lines[index + 1]) is not None
        )
