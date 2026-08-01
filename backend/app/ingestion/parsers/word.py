from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from app.ingestion.errors import EmptyDocumentError
from app.ingestion.models import (
    BlockKind,
    ParsedBlock,
    ParsedDocument,
    SourceLocation,
)
from app.ingestion.parsers._ooxml import OoxmlPackage, local_name

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
V_NS = "urn:schemas-microsoft-com:vml"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W_NS, "wp": WP_NS, "v": V_NS, "r": R_NS}
W_VAL = f"{{{W_NS}}}val"


@dataclass(frozen=True, slots=True)
class _StyleInfo:
    name: str | None
    based_on: str | None
    outline_level: int | None
    is_list: bool


@dataclass(frozen=True, slots=True)
class _PendingBlock:
    kind: BlockKind
    text: str
    section_path: tuple[str, ...]


class WordDocumentParser:
    file_types = frozenset({"docx"})
    parser_name = "docx-ooxml-v1"

    def parse(
        self,
        path: Path,
        *,
        display_name: str | None = None,
    ) -> ParsedDocument:
        with OoxmlPackage(
            path,
            required_members=("[Content_Types].xml", "word/document.xml"),
        ) as package:
            document_root = package.read_xml("word/document.xml")
            styles = (
                self._read_styles(package.read_xml("word/styles.xml"))
                if "word/styles.xml" in package.names
                else {}
            )

        pending: list[_PendingBlock] = []
        section_levels: list[str | None] = [None] * 9
        image_number = 0
        body = document_root.find("w:body", NS)
        if body is None:
            raise EmptyDocumentError(f"{path.name} has no document body.")

        for element in self._iter_body_content(body):
            if element.tag == f"{{{W_NS}}}p":
                paragraph_text = self._paragraph_text(element)
                style_id = self._paragraph_style_id(element)
                heading_level = self._heading_level(element, style_id, styles)
                if paragraph_text:
                    if heading_level is not None:
                        section_levels[heading_level - 1] = paragraph_text
                        for index in range(heading_level, len(section_levels)):
                            section_levels[index] = None
                        kind = BlockKind.HEADING
                    elif self._is_list(element, style_id, styles):
                        kind = BlockKind.LIST
                    else:
                        kind = BlockKind.PARAGRAPH
                    pending.append(
                        _PendingBlock(
                            kind=kind,
                            text=paragraph_text,
                            section_path=self._section_path(section_levels),
                        )
                    )
                for description in self._image_descriptions(element):
                    image_number += 1
                    pending.append(
                        _PendingBlock(
                            kind=BlockKind.IMAGE,
                            text=self._image_placeholder(image_number, description),
                            section_path=self._section_path(section_levels),
                        )
                    )
            elif element.tag == f"{{{W_NS}}}tbl":
                table_text = self._table_text(element)
                if table_text:
                    pending.append(
                        _PendingBlock(
                            kind=BlockKind.TABLE,
                            text=table_text,
                            section_path=self._section_path(section_levels),
                        )
                    )
                for description in self._image_descriptions(element):
                    image_number += 1
                    pending.append(
                        _PendingBlock(
                            kind=BlockKind.IMAGE,
                            text=self._image_placeholder(image_number, description),
                            section_path=self._section_path(section_levels),
                        )
                    )

        if not pending:
            raise EmptyDocumentError(f"{path.name} contains no readable content.")
        blocks = tuple(
            ParsedBlock(
                kind=item.kind,
                text=item.text,
                source=SourceLocation(block_index=index),
                section_path=item.section_path,
            )
            for index, item in enumerate(pending)
        )
        return ParsedDocument(
            file_name=display_name or path.name,
            file_type="docx",
            parser_name=self.parser_name,
            blocks=blocks,
        )

    @staticmethod
    def _iter_body_content(body: ElementTree.Element) -> list[ElementTree.Element]:
        content: list[ElementTree.Element] = []
        for child in body:
            if child.tag in (f"{{{W_NS}}}p", f"{{{W_NS}}}tbl"):
                content.append(child)
            elif child.tag == f"{{{W_NS}}}sdt":
                container = child.find("w:sdtContent", NS)
                if container is not None:
                    content.extend(WordDocumentParser._iter_body_content(container))
        return content

    @staticmethod
    def _read_styles(root: ElementTree.Element) -> dict[str, _StyleInfo]:
        styles: dict[str, _StyleInfo] = {}
        for style in root.findall("w:style", NS):
            style_id = style.get(f"{{{W_NS}}}styleId")
            if not style_id:
                continue
            name = style.find("w:name", NS)
            based_on = style.find("w:basedOn", NS)
            outline = style.find("w:pPr/w:outlineLvl", NS)
            styles[style_id] = _StyleInfo(
                name=name.get(W_VAL) if name is not None else None,
                based_on=based_on.get(W_VAL) if based_on is not None else None,
                outline_level=WordDocumentParser._parse_outline_level(outline),
                is_list=style.find("w:pPr/w:numPr", NS) is not None,
            )
        return styles

    @staticmethod
    def _parse_outline_level(element: ElementTree.Element | None) -> int | None:
        if element is None:
            return None
        value = element.get(W_VAL)
        if value is None or not value.isdigit():
            return None
        level = int(value) + 1
        return level if 1 <= level <= 9 else None

    @staticmethod
    def _paragraph_style_id(paragraph: ElementTree.Element) -> str | None:
        style = paragraph.find("w:pPr/w:pStyle", NS)
        return style.get(W_VAL) if style is not None else None

    @classmethod
    def _heading_level(
        cls,
        paragraph: ElementTree.Element,
        style_id: str | None,
        styles: dict[str, _StyleInfo],
    ) -> int | None:
        direct_outline = cls._parse_outline_level(
            paragraph.find("w:pPr/w:outlineLvl", NS)
        )
        if direct_outline is not None:
            return direct_outline
        for style in cls._style_chain(style_id, styles):
            if style.outline_level is not None:
                return style.outline_level
            normalized_name = (style.name or "").strip().casefold().replace(" ", "")
            if normalized_name == "title":
                return 1
            if normalized_name.startswith("heading"):
                suffix = normalized_name.removeprefix("heading")
                if suffix.isdigit() and 1 <= int(suffix) <= 9:
                    return int(suffix)
        return None

    @classmethod
    def _is_list(
        cls,
        paragraph: ElementTree.Element,
        style_id: str | None,
        styles: dict[str, _StyleInfo],
    ) -> bool:
        if paragraph.find("w:pPr/w:numPr", NS) is not None:
            return True
        return any(style.is_list for style in cls._style_chain(style_id, styles))

    @staticmethod
    def _style_chain(
        style_id: str | None,
        styles: dict[str, _StyleInfo],
    ) -> list[_StyleInfo]:
        chain: list[_StyleInfo] = []
        seen: set[str] = set()
        current = style_id
        while current and current not in seen:
            seen.add(current)
            style = styles.get(current)
            if style is None:
                break
            chain.append(style)
            current = style.based_on
        return chain

    @staticmethod
    def _paragraph_text(paragraph: ElementTree.Element) -> str:
        parts: list[str] = []
        for element in paragraph.iter():
            name = local_name(element.tag)
            if name in ("t", "delText") and element.text:
                parts.append(element.text)
            elif name == "tab":
                parts.append("\t")
            elif name in ("br", "cr"):
                parts.append("\n")
        return "".join(parts).strip()

    @classmethod
    def _table_text(cls, table: ElementTree.Element) -> str:
        rows: list[str] = []
        for row in table.findall("w:tr", NS):
            cells: list[str] = []
            for cell in row.findall("w:tc", NS):
                paragraphs = [
                    cls._paragraph_text(paragraph)
                    for paragraph in cell.findall(".//w:p", NS)
                ]
                cells.append("\n".join(text for text in paragraphs if text))
            if any(cell.strip() for cell in cells):
                rows.append(" | ".join(cells))
        return "\n".join(rows)

    @staticmethod
    def _image_descriptions(element: ElementTree.Element) -> tuple[str | None, ...]:
        descriptions: list[str | None] = []
        for drawing in element.findall(".//w:drawing", NS):
            doc_properties = drawing.find(".//wp:docPr", NS)
            descriptions.append(
                WordDocumentParser._drawing_description(doc_properties)
            )
        for image in element.findall(".//v:imagedata", NS):
            descriptions.append(image.get(f"{{{V_NS}}}title") or image.get("title"))
        return tuple(descriptions)

    @staticmethod
    def _drawing_description(element: ElementTree.Element | None) -> str | None:
        if element is None:
            return None
        for attribute in ("descr", "title", "name"):
            value = element.get(attribute)
            if value and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _image_placeholder(number: int, description: str | None) -> str:
        return f"[图片 {number}：{description}]" if description else f"[图片 {number}]"

    @staticmethod
    def _section_path(levels: list[str | None]) -> tuple[str, ...]:
        return tuple(level for level in levels if level is not None)
