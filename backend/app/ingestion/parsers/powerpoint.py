from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from app.ingestion.errors import EmptyDocumentError, InvalidDocumentFormatError
from app.ingestion.models import (
    BlockKind,
    ParsedBlock,
    ParsedDocument,
    ParseWarning,
    SourceLocation,
)
from app.ingestion.parsers._ooxml import OoxmlPackage, local_name, resolve_ooxml_target
from app.ingestion.parsers.base import ParseProgressCallback

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"p": P_NS, "a": A_NS, "r": R_NS, "rel": REL_NS}
R_ID = f"{{{R_NS}}}id"


@dataclass(frozen=True, slots=True)
class _PendingSlideBlock:
    kind: BlockKind
    text: str


class PowerPointParser:
    file_types = frozenset({"pptx"})
    parser_name = "pptx-ooxml-v1"

    def parse(
        self,
        path: Path,
        *,
        display_name: str | None = None,
        progress_callback: ParseProgressCallback | None = None,
    ) -> ParsedDocument:
        required = (
            "[Content_Types].xml",
            "ppt/presentation.xml",
            "ppt/_rels/presentation.xml.rels",
        )
        with OoxmlPackage(path, required_members=required) as package:
            presentation = package.read_xml("ppt/presentation.xml")
            relationships = package.read_xml("ppt/_rels/presentation.xml.rels")
            slide_members = self._slide_members(presentation, relationships)
            slide_roots = []
            for member in slide_members:
                if member not in package.names:
                    raise InvalidDocumentFormatError(
                        f"{path.name} is missing referenced slide {member}."
                    )
                slide_roots.append(package.read_xml(member))

        blocks: list[ParsedBlock] = []
        warnings: list[ParseWarning] = []
        image_number = 0
        total_slides = len(slide_roots)
        for slide_number, slide_root in enumerate(slide_roots, start=1):
            pending, slide_image_count = self._parse_slide(
                slide_root,
                image_number=image_number,
            )
            image_number += slide_image_count
            if not pending:
                warnings.append(
                    ParseWarning(
                        code="EMPTY_SLIDE",
                        message=f"Slide {slide_number} contains no readable content.",
                        slide_number=slide_number,
                    )
                )
                if progress_callback is not None:
                    progress_callback(
                        slide_number,
                        total_slides,
                        f"已解析第 {slide_number}/{total_slides} 张幻灯片",
                    )
                continue
            title = next(
                (item.text for item in pending if item.kind is BlockKind.HEADING),
                None,
            )
            section_path = (title,) if title else ()
            for item in pending:
                blocks.append(
                    ParsedBlock(
                        kind=item.kind,
                        text=item.text,
                        source=SourceLocation(
                            block_index=len(blocks),
                            slide_number=slide_number,
                        ),
                        section_path=section_path,
                    )
                )
            if progress_callback is not None:
                progress_callback(
                    slide_number,
                    total_slides,
                    f"已解析第 {slide_number}/{total_slides} 张幻灯片",
                )

        if not blocks:
            raise EmptyDocumentError(f"{path.name} contains no readable content.")
        return ParsedDocument(
            file_name=display_name or path.name,
            file_type="pptx",
            parser_name=self.parser_name,
            blocks=tuple(blocks),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _slide_members(
        presentation: ElementTree.Element,
        relationships: ElementTree.Element,
    ) -> tuple[str, ...]:
        targets = {
            relationship.get("Id"): relationship.get("Target")
            for relationship in relationships.findall("rel:Relationship", NS)
            if relationship.get("TargetMode") != "External"
        }
        members: list[str] = []
        for slide_id in presentation.findall("p:sldIdLst/p:sldId", NS):
            relationship_id = slide_id.get(R_ID)
            target = targets.get(relationship_id)
            if not relationship_id or not target:
                raise InvalidDocumentFormatError(
                    "A presentation slide has no valid relationship target."
                )
            member = resolve_ooxml_target("ppt/presentation.xml", target)
            if not member.startswith("ppt/slides/"):
                raise InvalidDocumentFormatError(
                    "A presentation relationship does not point to a slide."
                )
            members.append(member)
        return tuple(members)

    @classmethod
    def _parse_slide(
        cls,
        root: ElementTree.Element,
        *,
        image_number: int,
    ) -> tuple[list[_PendingSlideBlock], int]:
        shape_tree = root.find("p:cSld/p:spTree", NS)
        if shape_tree is None:
            return [], 0
        pending: list[_PendingSlideBlock] = []
        image_count = 0
        elements = cls._iter_slide_elements(shape_tree)
        text_shapes = [
            element
            for element in elements
            if element.tag == f"{{{P_NS}}}sp" and cls._shape_paragraphs(element)
        ]
        title_shapes = [shape for shape in text_shapes if cls._has_title_role(shape)]
        inferred_title_shape = title_shapes[0] if title_shapes else next(iter(text_shapes), None)
        if inferred_title_shape is not None:
            main_title = cls._shape_paragraphs(inferred_title_shape)[0][0]
            pending.append(_PendingSlideBlock(BlockKind.HEADING, main_title))

        for element in elements:
            if element.tag == f"{{{P_NS}}}sp":
                has_title_role = cls._has_title_role(element)
                for paragraph_index, (text, is_list) in enumerate(
                    cls._shape_paragraphs(element)
                ):
                    if element is inferred_title_shape and paragraph_index == 0:
                        continue
                    is_heading = (
                        paragraph_index == 0
                        and has_title_role
                    )
                    pending.append(
                        _PendingSlideBlock(
                            kind=(
                                BlockKind.HEADING
                                if is_heading
                                else BlockKind.LIST
                                if is_list
                                else BlockKind.PARAGRAPH
                            ),
                            text=text,
                        )
                    )
            elif element.tag == f"{{{P_NS}}}graphicFrame":
                table = element.find(".//a:tbl", NS)
                if table is not None:
                    table_text = cls._table_text(table)
                    if table_text:
                        pending.append(
                            _PendingSlideBlock(BlockKind.TABLE, table_text)
                        )
            elif element.tag == f"{{{P_NS}}}pic":
                image_count += 1
                description = cls._picture_description(element)
                number = image_number + image_count
                text = (
                    f"[图片 {number}：{description}]"
                    if description
                    else f"[图片 {number}]"
                )
                pending.append(_PendingSlideBlock(BlockKind.IMAGE, text))
        return pending, image_count

    @staticmethod
    def _iter_slide_elements(shape_tree: ElementTree.Element) -> list[ElementTree.Element]:
        elements: list[ElementTree.Element] = []
        for child in shape_tree:
            if child.tag == f"{{{P_NS}}}grpSp":
                elements.extend(PowerPointParser._iter_slide_elements(child))
            elif child.tag in (
                f"{{{P_NS}}}sp",
                f"{{{P_NS}}}graphicFrame",
                f"{{{P_NS}}}pic",
            ):
                elements.append(child)
        return elements

    @staticmethod
    def _has_title_role(shape: ElementTree.Element) -> bool:
        placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
        if placeholder is not None and placeholder.get("type") in {"title", "ctrTitle"}:
            return True
        properties = shape.find("p:nvSpPr/p:cNvPr", NS)
        shape_name = (properties.get("name") if properties is not None else "") or ""
        normalized_name = shape_name.strip().casefold()
        return normalized_name.startswith(("title", "标题"))

    @classmethod
    def _shape_paragraphs(
        cls,
        shape: ElementTree.Element,
    ) -> tuple[tuple[str, bool], ...]:
        paragraphs: list[tuple[str, bool]] = []
        for paragraph in shape.findall("p:txBody/a:p", NS):
            text = cls._drawingml_paragraph_text(paragraph)
            if not text:
                continue
            paragraph_properties = paragraph.find("a:pPr", NS)
            is_list = False
            if paragraph_properties is not None:
                is_list = (
                    paragraph_properties.get("lvl") is not None
                    or any(
                        local_name(child.tag).startswith("bu")
                        and local_name(child.tag) != "buNone"
                        for child in paragraph_properties
                    )
                )
            paragraphs.append((text, is_list))
        return tuple(paragraphs)

    @staticmethod
    def _drawingml_paragraph_text(paragraph: ElementTree.Element) -> str:
        parts: list[str] = []
        for child in paragraph:
            name = local_name(child.tag)
            if name in ("r", "fld"):
                text = child.find("a:t", NS)
                if text is not None and text.text:
                    parts.append(text.text)
            elif name == "br":
                parts.append("\n")
        return "".join(parts).strip()

    @classmethod
    def _table_text(cls, table: ElementTree.Element) -> str:
        rows: list[str] = []
        for row in table.findall("a:tr", NS):
            cells: list[str] = []
            for cell in row.findall("a:tc", NS):
                paragraphs = [
                    cls._drawingml_paragraph_text(paragraph)
                    for paragraph in cell.findall("a:txBody/a:p", NS)
                ]
                cells.append("\n".join(text for text in paragraphs if text))
            if any(cell.strip() for cell in cells):
                rows.append(" | ".join(cells))
        return "\n".join(rows)

    @staticmethod
    def _picture_description(picture: ElementTree.Element) -> str | None:
        properties = picture.find("p:nvPicPr/p:cNvPr", NS)
        if properties is None:
            return None
        for attribute in ("descr", "title", "name"):
            value = properties.get(attribute)
            if value and value.strip():
                return value.strip()
        return None
