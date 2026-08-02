from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    CODE = "code"
    TABLE = "table"
    IMAGE = "image"
    FORMULA = "formula"


class ExtractionMethod(StrEnum):
    NATIVE_PDF = "native_pdf"
    OCR = "ocr"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Location inside the original file before chunking."""

    block_index: int
    line_start: int | None = None
    line_end: int | None = None
    page_number: int | None = None
    slide_number: int | None = None
    extraction_method: ExtractionMethod | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.block_index < 0:
            raise ValueError("block_index cannot be negative.")
        for field_name in ("line_start", "line_end", "page_number", "slide_number"):
            value = getattr(self, field_name)
            if value is not None and value < 1:
                raise ValueError(f"{field_name} must be positive when provided.")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end cannot be before line_start.")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1 when provided.")
        if self.confidence is not None and self.extraction_method is not ExtractionMethod.OCR:
            raise ValueError("Only OCR sources can declare confidence.")


@dataclass(frozen=True, slots=True)
class ParseWarning:
    code: str
    message: str
    line_start: int | None = None
    line_end: int | None = None
    page_number: int | None = None
    slide_number: int | None = None

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("Parse warning code and message cannot be blank.")
        for field_name in ("line_start", "line_end", "page_number", "slide_number"):
            value = getattr(self, field_name)
            if value is not None and value < 1:
                raise ValueError(f"{field_name} must be positive when provided.")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end cannot be before line_start.")


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    kind: BlockKind
    text: str
    source: SourceLocation
    section_path: tuple[str, ...] = ()
    language: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Parsed block text cannot be blank.")
        if self.kind is not BlockKind.CODE and self.language is not None:
            raise ValueError("Only code blocks can declare a language.")


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    file_name: str
    file_type: str
    parser_name: str
    blocks: tuple[ParsedBlock, ...]
    warnings: tuple[ParseWarning, ...] = ()

    def __post_init__(self) -> None:
        if not self.file_name.strip():
            raise ValueError("file_name cannot be blank.")
        if not self.file_type.strip():
            raise ValueError("file_type cannot be blank.")
        if not self.parser_name.strip():
            raise ValueError("parser_name cannot be blank.")
        if not self.blocks:
            raise ValueError("Parsed document must contain at least one block.")
        indexes = [block.source.block_index for block in self.blocks]
        if indexes != list(range(len(self.blocks))):
            raise ValueError("Parsed block indexes must be contiguous and zero-based.")

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks)

    @property
    def character_count(self) -> int:
        return sum(len(block.text) for block in self.blocks)
