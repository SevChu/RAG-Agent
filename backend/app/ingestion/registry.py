from __future__ import annotations

from pathlib import Path

from app.ingestion.errors import UnsupportedParserError
from app.ingestion.models import ParsedDocument
from app.ingestion.parsers import (
    MarkdownParser,
    PdfParser,
    PlainTextParser,
    PowerPointParser,
    WordDocumentParser,
)
from app.ingestion.parsers.base import DocumentParser


class DocumentParserRegistry:
    def __init__(self, parsers: tuple[DocumentParser, ...] = ()) -> None:
        self._parsers: dict[str, DocumentParser] = {}
        for parser in parsers:
            self.register(parser)

    @property
    def supported_file_types(self) -> frozenset[str]:
        return frozenset(self._parsers)

    def register(self, parser: DocumentParser) -> None:
        for file_type in parser.file_types:
            normalized = self._normalize_file_type(file_type)
            if normalized in self._parsers:
                raise ValueError(f"A parser is already registered for {normalized}.")
            self._parsers[normalized] = parser

    def parse(
        self,
        path: Path,
        *,
        file_type: str | None = None,
        display_name: str | None = None,
    ) -> ParsedDocument:
        normalized = self._normalize_file_type(file_type or path.suffix)
        parser = self._parsers.get(normalized)
        if parser is None:
            raise UnsupportedParserError(
                f"No document parser is registered for {normalized or 'unknown'} files."
            )
        return parser.parse(path, display_name=display_name)

    @staticmethod
    def _normalize_file_type(file_type: str) -> str:
        return file_type.strip().lower().removeprefix(".")


def build_default_registry(
    *,
    pdf_page_numbers: tuple[int, ...] | None = None,
    ocr_model_root: Path | None = None,
) -> DocumentParserRegistry:
    """Build the parsers completed through week 2, plan day 3."""

    return DocumentParserRegistry(
        (
            PlainTextParser(),
            MarkdownParser(),
            WordDocumentParser(),
            PowerPointParser(),
            PdfParser(
                page_numbers=pdf_page_numbers,
                ocr_model_root=ocr_model_root,
            ),
        )
    )
