from __future__ import annotations

import re
from pathlib import Path

from app.ingestion.errors import (
    DocumentReadError,
    EmptyDocumentError,
    InvalidDocumentEncodingError,
)
from app.ingestion.models import BlockKind, ParsedBlock, ParsedDocument, SourceLocation

_BOOK_HEADING_RE = re.compile(r"^Book\b", re.IGNORECASE)
_NUMBERED_HEADING_RE = re.compile(
    r"^(?:\d{1,3}(?:\.\d{1,3})*\.\s+\S|"
    r"[一二三四五六七八九十百]+、\s*[A-Za-z\u3400-\u9fff])"
)
_ROMAN_HEADING_RE = re.compile(r"^[IVXLCDM]{1,8}$")


def read_utf8_text(path: Path) -> str:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise DocumentReadError(f"Unable to read document: {path.name}.") from error
    if b"\x00" in content:
        raise InvalidDocumentEncodingError("Text documents cannot contain null bytes.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidDocumentEncodingError(
            "Text documents must use UTF-8 encoding."
        ) from error
    return text.replace("\r\n", "\n").replace("\r", "\n")


class PlainTextParser:
    file_types = frozenset({"txt"})
    parser_name = "plain-text-structured-v2"

    def parse(
        self,
        path: Path,
        *,
        display_name: str | None = None,
    ) -> ParsedDocument:
        text = read_utf8_text(path)
        lines = text.split("\n")
        blocks: list[ParsedBlock] = []
        paragraph_lines: list[str] = []
        paragraph_start = 0
        section_levels: list[tuple[int, str]] = []

        def section_path() -> tuple[str, ...]:
            return tuple(title for _, title in section_levels)

        def append_heading(text: str, line_number: int, level: int) -> None:
            nonlocal section_levels
            title = text.strip()
            section_levels = [item for item in section_levels if item[0] < level]
            section_levels.append((level, title))
            blocks.append(
                ParsedBlock(
                    kind=BlockKind.HEADING,
                    text=title,
                    source=SourceLocation(
                        block_index=len(blocks),
                        line_start=line_number,
                        line_end=line_number,
                    ),
                    section_path=section_path(),
                )
            )

        def flush_paragraph(line_end: int) -> None:
            nonlocal paragraph_lines
            if not paragraph_lines:
                return
            paragraph = "\n".join(paragraph_lines).strip()
            paragraph_lines = []
            if not paragraph:
                return
            blocks.append(
                ParsedBlock(
                    kind=BlockKind.PARAGRAPH,
                    text=paragraph,
                    source=SourceLocation(
                        block_index=len(blocks),
                        line_start=paragraph_start,
                        line_end=line_end,
                    ),
                    section_path=section_path(),
                )
            )

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                flush_paragraph(line_number - 1)
                continue
            heading_level = _plain_heading_level(lines, line_number - 1)
            if heading_level is not None:
                flush_paragraph(line_number - 1)
                append_heading(line, line_number, heading_level)
                continue
            if not paragraph_lines:
                paragraph_start = line_number
            paragraph_lines.append(line.rstrip())
        flush_paragraph(len(lines))

        if not blocks:
            raise EmptyDocumentError("The text document contains no meaningful content.")
        return ParsedDocument(
            file_name=display_name or path.name,
            file_type="txt",
            parser_name=self.parser_name,
            blocks=tuple(blocks),
        )


def _plain_heading_level(lines: list[str], index: int) -> int | None:
    stripped = lines[index].strip()
    if len(stripped) > 80:
        return None
    previous_blank = index == 0 or not lines[index - 1].strip()
    next_blank = index == len(lines) - 1 or not lines[index + 1].strip()
    isolated = previous_blank and next_blank
    if _BOOK_HEADING_RE.match(stripped):
        return 1
    plausible_numbered_heading = (
        isolated
        and len(stripped) <= 60
        and stripped[-1] not in ".!?。！？；;:："
    )
    if plausible_numbered_heading:
        if numbered_match := re.match(r"^(\d+(?:\.\d+)*)\.", stripped):
            return min(6, numbered_match.group(1).count(".") + 2)
        if _NUMBERED_HEADING_RE.match(stripped):
            return 2
    if isolated and _ROMAN_HEADING_RE.fullmatch(stripped):
        return 2
    if (
        isolated
        and stripped.isupper()
        and any(character.isalpha() for character in stripped)
    ):
        return 1
    if (
        isolated
        and 1 < len(stripped.split()) <= 12
        and stripped[:1].isupper()
        and stripped[-1] not in ".!?。！？；;:："
        and _previous_nonblank_is_number(lines, index)
    ):
        return 3
    return None


def _previous_nonblank_is_number(lines: list[str], index: int) -> bool:
    for previous_index in range(index - 1, -1, -1):
        candidate = lines[previous_index].strip()
        if candidate:
            return bool(
                _ROMAN_HEADING_RE.fullmatch(candidate)
                or re.fullmatch(r"\d{1,3}", candidate)
            )
    return False
