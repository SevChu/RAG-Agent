from __future__ import annotations

from pathlib import Path

from app.ingestion.errors import (
    DocumentReadError,
    EmptyDocumentError,
    InvalidDocumentEncodingError,
)
from app.ingestion.models import BlockKind, ParsedBlock, ParsedDocument, SourceLocation


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
    parser_name = "plain-text-v1"

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
                )
            )

        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                flush_paragraph(line_number - 1)
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
