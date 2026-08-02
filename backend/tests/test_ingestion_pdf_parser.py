from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from app.ingestion.chunking import ChunkingContext, StructuredDocumentChunker
from app.ingestion.errors import EmptyDocumentError, InvalidDocumentFormatError
from app.ingestion.models import ExtractionMethod
from app.ingestion.parsers.pdf import OcrLine, PdfParser


class FakeRenderer:
    def __init__(self) -> None:
        self.rendered_pages: list[int] = []

    def render(self, path: Path, page_index: int, *, dpi: int) -> NDArray[np.uint8]:
        del path, dpi
        self.rendered_pages.append(page_index)
        return np.full((1000, 800, 3), page_index, dtype=np.uint8)

    def close(self) -> None:
        return


class FakeOcrEngine:
    def __init__(self, pages: dict[int, tuple[OcrLine, ...]]) -> None:
        self.pages = pages
        self.recognized_pages: list[int] = []

    def recognize(self, image: NDArray[np.uint8]) -> tuple[OcrLine, ...]:
        page_index = int(image[0, 0, 0])
        self.recognized_pages.append(page_index)
        return self.pages.get(page_index, ())


def _ocr_line(
    text: str,
    confidence: float = 0.9,
    box: tuple[float, float, float, float] = (50, 200, 300, 230),
) -> OcrLine:
    return OcrLine(text=text, confidence=confidence, box=box)


def _write_pdf(
    path: Path,
    pages: tuple[str | None, ...],
    *,
    password: str | None = None,
) -> None:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    font_reference = writer._add_object(font)  # noqa: SLF001
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        resources = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_reference}
                )
            }
        )
        page[NameObject("/Resources")] = resources
        content = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        content[NameObject("/Length")] = NumberObject(len(content.get_data()))
        page[NameObject("/Contents")] = writer._add_object(content)  # noqa: SLF001
    writer.add_metadata({"/Title": TextStringObject("PDF parser test")})
    if password is not None:
        writer.encrypt(password)
    with path.open("wb") as stream:
        writer.write(stream)


def test_native_text_is_preferred_without_rendering(tmp_path: Path) -> None:
    path = tmp_path / "native.pdf"
    _write_pdf(path, ("This native PDF paragraph is long enough for direct extraction.",))
    renderer = FakeRenderer()
    ocr = FakeOcrEngine({})

    result = PdfParser(renderer=renderer, ocr_engine=ocr).parse(path)

    assert renderer.rendered_pages == []
    assert ocr.recognized_pages == []
    assert result.blocks[0].source.page_number == 1
    assert result.blocks[0].source.extraction_method is ExtractionMethod.NATIVE_PDF
    assert result.blocks[0].source.confidence is None


def test_scanned_page_uses_ocr_and_preserves_confidence(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    _write_pdf(path, (None,))
    renderer = FakeRenderer()
    ocr = FakeOcrEngine(
        {
            0: (
                _ocr_line("Data Structures", box=(50, 200, 300, 230)),
                _ocr_line("low", confidence=0.1, box=(50, 250, 150, 280)),
                _ocr_line("Chapter one", confidence=0.8, box=(50, 320, 250, 350)),
            )
        }
    )

    result = PdfParser(renderer=renderer, ocr_engine=ocr).parse(path)

    assert renderer.rendered_pages == [0]
    assert ocr.recognized_pages == [0]
    assert [block.text for block in result.blocks] == ["Data Structures", "Chapter one"]
    assert all(
        block.source.extraction_method is ExtractionMethod.OCR
        for block in result.blocks
    )
    assert result.blocks[0].source.confidence == pytest.approx(0.9)
    assert result.warnings[0].code == "LOW_CONFIDENCE_OCR_DROPPED"
    assert result.warnings[0].page_number == 1


def test_mixed_pdf_falls_back_only_for_page_without_text(tmp_path: Path) -> None:
    path = tmp_path / "mixed.pdf"
    _write_pdf(
        path,
        ("This page has a meaningful native text layer for extraction.", None),
    )
    renderer = FakeRenderer()
    ocr = FakeOcrEngine({1: (_ocr_line("Scanned second page"),)})

    result = PdfParser(renderer=renderer, ocr_engine=ocr).parse(path)

    assert renderer.rendered_pages == [1]
    assert [block.source.page_number for block in result.blocks] == [1, 2]
    assert [block.source.extraction_method for block in result.blocks] == [
        ExtractionMethod.NATIVE_PDF,
        ExtractionMethod.OCR,
    ]


def test_ocr_provenance_reaches_chunk_metadata(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    _write_pdf(path, (None,))
    parser = PdfParser(
        renderer=FakeRenderer(),
        ocr_engine=FakeOcrEngine({0: (_ocr_line("Binary tree traversal", 0.83),)}),
    )

    chunking = StructuredDocumentChunker().chunk(
        parser.parse(path),
        context=ChunkingContext(course_id="course-1", document_id="document-1"),
    )

    source = chunking.chunks[0].source
    assert source.page_numbers == (1,)
    assert source.extraction_methods == (ExtractionMethod.OCR,)
    assert source.minimum_ocr_confidence == pytest.approx(0.83)


def test_partial_page_inspection_does_not_process_other_pages(tmp_path: Path) -> None:
    path = tmp_path / "three-pages.pdf"
    _write_pdf(path, (None, None, None))
    renderer = FakeRenderer()
    parser = PdfParser(
        renderer=renderer,
        ocr_engine=FakeOcrEngine({1: (_ocr_line("Only page two"),)}),
        page_numbers=(2,),
    )

    result = parser.parse(path)

    assert renderer.rendered_pages == [1]
    assert result.blocks[0].source.page_number == 2
    assert result.warnings[0].code == "PARTIAL_PDF_PARSE"


def test_empty_pdf_text_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    _write_pdf(path, (None,))

    with pytest.raises(EmptyDocumentError, match="no meaningful text"):
        PdfParser(renderer=FakeRenderer(), ocr_engine=FakeOcrEngine({})).parse(path)


def test_encrypted_pdf_is_rejected_before_ocr(tmp_path: Path) -> None:
    path = tmp_path / "encrypted.pdf"
    _write_pdf(path, (None,), password="secret")

    with pytest.raises(InvalidDocumentFormatError, match="Encrypted"):
        PdfParser(renderer=FakeRenderer(), ocr_engine=FakeOcrEngine({})).parse(path)


def test_damaged_pdf_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "damaged.pdf"
    path.write_bytes(b"%PDF-1.7\ndamaged")

    with pytest.raises(InvalidDocumentFormatError, match="damaged or malformed"):
        PdfParser(renderer=FakeRenderer(), ocr_engine=FakeOcrEngine({})).parse(path)


def test_requested_page_must_exist(tmp_path: Path) -> None:
    path = tmp_path / "one-page.pdf"
    _write_pdf(path, (None,))

    with pytest.raises(InvalidDocumentFormatError, match="exceeds"):
        PdfParser(
            renderer=FakeRenderer(),
            ocr_engine=FakeOcrEngine({}),
            page_numbers=(2,),
        ).parse(path)
