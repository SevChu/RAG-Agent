from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import pypdfium2 as pdfium  # type: ignore[import-untyped]
from numpy.typing import NDArray
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from app.ingestion.errors import (
    DocumentReadError,
    EmptyDocumentError,
    InvalidDocumentFormatError,
)
from app.ingestion.models import (
    BlockKind,
    ExtractionMethod,
    ParsedBlock,
    ParsedDocument,
    ParseWarning,
    SourceLocation,
)
from app.ingestion.parsers._ocr_layout import (
    LayoutLine,
    OcrLayoutAnalyzer,
    OcrLayoutBlock,
)

_WHITESPACE_RE = re.compile(r"[\t\u00a0 ]+")
_DEFAULT_MODEL_ROOT = Path(__file__).resolve().parents[4] / "data" / "models" / "paddleocr"


@dataclass(frozen=True, slots=True)
class PdfParserConfig:
    minimum_native_characters: int = 20
    minimum_ocr_confidence: float = 0.35
    render_dpi: int = 220

    def __post_init__(self) -> None:
        if self.minimum_native_characters < 1:
            raise ValueError("minimum_native_characters must be positive.")
        if not 0 <= self.minimum_ocr_confidence <= 1:
            raise ValueError("minimum_ocr_confidence must be between 0 and 1.")
        if not 72 <= self.render_dpi <= 600:
            raise ValueError("render_dpi must be between 72 and 600.")


@dataclass(frozen=True, slots=True)
class OcrLine:
    text: str
    confidence: float
    box: tuple[float, float, float, float]


class OcrEngine(Protocol):
    def recognize(self, image: NDArray[np.uint8]) -> tuple[OcrLine, ...]: ...


class PdfPageRenderer(Protocol):
    def render(self, path: Path, page_index: int, *, dpi: int) -> NDArray[np.uint8]: ...

    def close(self) -> None: ...


class PdfiumPageRenderer:
    def __init__(self) -> None:
        self._document: Any | None = None
        self._path: Path | None = None

    def render(self, path: Path, page_index: int, *, dpi: int) -> NDArray[np.uint8]:
        try:
            if self._document is None or self._path != path:
                self.close()
                self._document = pdfium.PdfDocument(path)
                self._path = path
            page = self._document[page_index]
            bitmap = page.render(scale=dpi / 72)
            image = bitmap.to_numpy().copy()
            bitmap.close()
            page.close()
        except Exception as error:
            raise DocumentReadError(
                f"PDF page {page_index + 1} could not be rendered for OCR."
            ) from error
        if image.ndim != 3:
            raise DocumentReadError(
                f"PDF page {page_index + 1} rendered to an unsupported image format."
            )
        if image.shape[2] == 4:
            image = image[:, :, :3]
        return np.ascontiguousarray(image)

    def close(self) -> None:
        if self._document is not None:
            self._document.close()
        self._document = None
        self._path = None


class PaddleOcrEngine:
    detection_model_name = "PP-OCRv6_small_det"
    recognition_model_name = "PP-OCRv6_small_rec"

    def __init__(self, model_root: Path = _DEFAULT_MODEL_ROOT) -> None:
        self.model_root = model_root.resolve()
        self.detection_model_dir = self.model_root / self.detection_model_name
        self.recognition_model_dir = self.model_root / self.recognition_model_name
        self._pipeline: Any | None = None

    def recognize(self, image: NDArray[np.uint8]) -> tuple[OcrLine, ...]:
        pipeline = self._load_pipeline()
        try:
            results = pipeline.predict(image)
        except Exception as error:
            raise DocumentReadError("PaddleOCR failed to recognize a PDF page.") from error

        lines: list[OcrLine] = []
        for result in results:
            payload = cast(dict[str, Any], result)
            texts = payload.get("rec_texts", ())
            scores = payload.get("rec_scores", ())
            boxes = payload.get("rec_boxes", ())
            for text, score, box in zip(texts, scores, boxes, strict=False):
                normalized = _normalize_line(str(text))
                if not normalized:
                    continue
                coordinates = tuple(float(value) for value in box)
                if len(coordinates) != 4:
                    continue
                lines.append(
                    OcrLine(
                        text=normalized,
                        confidence=max(0.0, min(1.0, float(score))),
                        box=coordinates,
                    )
                )
        return tuple(sorted(lines, key=lambda line: (line.box[1], line.box[0])))

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        missing = [
            path
            for path in (self.detection_model_dir, self.recognition_model_dir)
            if not path.is_dir()
        ]
        if missing:
            locations = ", ".join(str(path) for path in missing)
            raise DocumentReadError(f"Required local OCR model directory is missing: {locations}.")

        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(self.model_root))
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped]

            self._pipeline = PaddleOCR(
                text_detection_model_name=self.detection_model_name,
                text_detection_model_dir=str(self.detection_model_dir),
                text_recognition_model_name=self.recognition_model_name,
                text_recognition_model_dir=str(self.recognition_model_dir),
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device="cpu",
                enable_mkldnn=False,
            )
        except Exception as error:
            raise DocumentReadError("The local PaddleOCR pipeline could not be loaded.") from error
        return self._pipeline


class PdfParser:
    file_types = frozenset({"pdf"})
    parser_name = "pdf-native-with-paddleocr-fallback-v1"

    def __init__(
        self,
        *,
        config: PdfParserConfig | None = None,
        ocr_engine: OcrEngine | None = None,
        renderer: PdfPageRenderer | None = None,
        page_numbers: tuple[int, ...] | None = None,
        ocr_model_root: Path | None = None,
    ) -> None:
        self.config = config or PdfParserConfig()
        configured_model_root = ocr_model_root or Path(
            os.environ.get("PADDLE_OCR_BASE_DIR", _DEFAULT_MODEL_ROOT)
        )
        self.ocr_engine = ocr_engine or PaddleOcrEngine(configured_model_root)
        self.renderer = renderer or PdfiumPageRenderer()
        self.layout_analyzer = OcrLayoutAnalyzer()
        if page_numbers is not None and (
            not page_numbers or any(page_number < 1 for page_number in page_numbers)
        ):
            raise ValueError("page_numbers must contain positive one-based page numbers.")
        self.page_numbers = (
            tuple(dict.fromkeys(page_numbers)) if page_numbers is not None else None
        )

    def parse(self, path: Path, *, display_name: str | None = None) -> ParsedDocument:
        reader = self._open_reader(path)
        page_indexes = self._selected_page_indexes(len(reader.pages))
        blocks: list[ParsedBlock] = []
        warnings: list[ParseWarning] = []

        if self.page_numbers is not None:
            warnings.append(
                ParseWarning(
                    code="PARTIAL_PDF_PARSE",
                    message=(
                        f"Inspection parsed {len(page_indexes)} of {len(reader.pages)} PDF pages."
                    ),
                )
            )

        try:
            self._parse_pages(reader, path, page_indexes, blocks, warnings)
        finally:
            self.renderer.close()

        if not blocks:
            raise EmptyDocumentError("PDF parsing produced no meaningful text.")
        return ParsedDocument(
            file_name=display_name or path.name,
            file_type="pdf",
            parser_name=self.parser_name,
            blocks=tuple(blocks),
            warnings=tuple(warnings),
        )

    def _parse_pages(
        self,
        reader: PdfReader,
        path: Path,
        page_indexes: tuple[int, ...],
        blocks: list[ParsedBlock],
        warnings: list[ParseWarning],
    ) -> None:
        for page_index in page_indexes:
            page_number = page_index + 1
            try:
                native_text = reader.pages[page_index].extract_text() or ""
            except FileNotDecryptedError as error:
                raise InvalidDocumentFormatError(
                    "Encrypted PDF files are not supported."
                ) from error
            except Exception as error:
                raise DocumentReadError(
                    f"PDF page {page_number} native text extraction failed."
                ) from error

            native_paragraphs = _normalize_native_paragraphs(native_text)
            if _has_meaningful_text(native_paragraphs, self.config.minimum_native_characters):
                self._append_native_blocks(blocks, native_paragraphs, page_number)
                continue

            image = self.renderer.render(path, page_index, dpi=self.config.render_dpi)
            ocr_lines = self.ocr_engine.recognize(image)
            accepted = tuple(
                line
                for line in ocr_lines
                if line.confidence >= self.config.minimum_ocr_confidence
                and _informative_character_count(line.text) > 0
            )
            dropped = len(ocr_lines) - len(accepted)
            if dropped:
                warnings.append(
                    ParseWarning(
                        code="LOW_CONFIDENCE_OCR_DROPPED",
                        message=f"Dropped {dropped} low-confidence OCR lines.",
                        page_number=page_number,
                    )
                )
            layout_blocks = self.layout_analyzer.analyze(
                tuple(
                    LayoutLine(
                        text=line.text,
                        confidence=line.confidence,
                        box=line.box,
                    )
                    for line in accepted
                ),
                page_width=image.shape[1],
                page_height=image.shape[0],
            )
            if not layout_blocks:
                warnings.append(
                    ParseWarning(
                        code="EMPTY_PDF_PAGE",
                        message="The page has no meaningful native or OCR text.",
                        page_number=page_number,
                    )
                )
                continue
            self._append_ocr_blocks(blocks, layout_blocks, page_number)

    @staticmethod
    def _open_reader(path: Path) -> PdfReader:
        try:
            reader = PdfReader(path, strict=False)
        except (OSError, PdfReadError, ValueError) as error:
            raise InvalidDocumentFormatError("The PDF file is damaged or malformed.") from error
        if reader.is_encrypted:
            raise InvalidDocumentFormatError("Encrypted PDF files are not supported.")
        if not reader.pages:
            raise EmptyDocumentError("The PDF contains no pages.")
        return reader

    def _selected_page_indexes(self, page_count: int) -> tuple[int, ...]:
        if self.page_numbers is None:
            return tuple(range(page_count))
        invalid = [page_number for page_number in self.page_numbers if page_number > page_count]
        if invalid:
            raise InvalidDocumentFormatError(
                f"Requested PDF page exceeds the {page_count}-page document: {invalid[0]}."
            )
        return tuple(page_number - 1 for page_number in self.page_numbers)

    @staticmethod
    def _append_native_blocks(
        blocks: list[ParsedBlock], paragraphs: tuple[str, ...], page_number: int
    ) -> None:
        for paragraph in paragraphs:
            blocks.append(
                ParsedBlock(
                    kind=BlockKind.PARAGRAPH,
                    text=paragraph,
                    source=SourceLocation(
                        block_index=len(blocks),
                        page_number=page_number,
                        extraction_method=ExtractionMethod.NATIVE_PDF,
                    ),
                )
            )

    @staticmethod
    def _append_ocr_blocks(
        blocks: list[ParsedBlock],
        layout_blocks: Iterable[OcrLayoutBlock],
        page_number: int,
    ) -> None:
        for layout_block in layout_blocks:
            blocks.append(
                ParsedBlock(
                    kind=layout_block.kind,
                    text=layout_block.text,
                    source=SourceLocation(
                        block_index=len(blocks),
                        page_number=page_number,
                        extraction_method=ExtractionMethod.OCR,
                        confidence=layout_block.confidence,
                    ),
                )
            )


def _normalize_line(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.replace("\x00", "").strip())


def _normalize_native_paragraphs(text: str) -> tuple[str, ...]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    current: list[str] = []
    for raw_line in normalized.split("\n"):
        line = _normalize_line(raw_line)
        if line:
            current.append(line)
        elif current:
            paragraphs.append("\n".join(current))
            current = []
    if current:
        paragraphs.append("\n".join(current))
    return tuple(paragraphs)


def _informative_character_count(text: str) -> int:
    return sum(character.isalnum() for character in text)


def _has_meaningful_text(paragraphs: tuple[str, ...], minimum_characters: int) -> bool:
    text = "\n".join(paragraphs)
    non_whitespace = sum(not character.isspace() for character in text)
    if non_whitespace == 0:
        return False
    informative = _informative_character_count(text)
    return informative >= minimum_characters and informative / non_whitespace >= 0.35
