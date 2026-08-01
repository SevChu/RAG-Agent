from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from app.ingestion import BlockKind, build_default_registry
from app.ingestion.errors import EmptyDocumentError, InvalidDocumentFormatError
from app.ingestion.parsers import PowerPointParser, WordDocumentParser


def _write_package(path: Path, members: dict[str, str]) -> None:
    with ZipFile(path, "w") as archive:
        for member_name, content in members.items():
            archive.writestr(member_name, content)


def _content_types() -> str:
    return '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'


def test_docx_parser_preserves_headings_lists_tables_and_image_placeholders(
    tmp_path: Path,
) -> None:
    path = tmp_path / "course.docx"
    document = """\
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>数据结构</w:t></w:r></w:p>
    <w:p><w:r><w:t>课程简介</w:t></w:r><w:r><w:tab/><w:t>必修</w:t></w:r>
      <w:r><w:drawing><wp:inline>
        <wp:docPr id="1" name="教材封面" descr="栈示意图"/>
      </wp:inline></w:drawing></w:r>
    </w:p>
    <w:p><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>顺序表</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>操作</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>复杂度</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>查找</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>O(n)</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    styles = """\
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>
  </w:style>
</w:styles>"""
    _write_package(
        path,
        {
            "[Content_Types].xml": _content_types(),
            "word/document.xml": document,
            "word/styles.xml": styles,
        },
    )

    result = WordDocumentParser().parse(path, display_name="课程指导.docx")

    assert result.file_name == "课程指导.docx"
    assert result.parser_name == "docx-ooxml-v1"
    assert [block.kind for block in result.blocks] == [
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.IMAGE,
        BlockKind.LIST,
        BlockKind.TABLE,
    ]
    assert result.blocks[1].text == "课程简介\t必修"
    assert result.blocks[2].text == "[图片 1：栈示意图]"
    assert result.blocks[-1].text == "操作 | 复杂度\n查找 | O(n)"
    assert all(block.section_path == ("数据结构",) for block in result.blocks)
    assert [block.source.block_index for block in result.blocks] == list(range(5))


def test_docx_parser_reads_content_controls_and_inherited_heading_styles(
    tmp_path: Path,
) -> None:
    path = tmp_path / "content-control.docx"
    document = """\
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:sdt><w:sdtContent>
    <w:p><w:pPr><w:pStyle w:val="CustomHeading"/></w:pPr><w:r><w:t>算法</w:t></w:r></w:p>
    <w:p><w:r><w:t>动态规划</w:t></w:r></w:p>
  </w:sdtContent></w:sdt></w:body>
</w:document>"""
    styles = """\
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="BaseHeading">
    <w:pPr><w:outlineLvl w:val="1"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="CustomHeading"><w:basedOn w:val="BaseHeading"/></w:style>
</w:styles>"""
    _write_package(
        path,
        {
            "[Content_Types].xml": _content_types(),
            "word/document.xml": document,
            "word/styles.xml": styles,
        },
    )

    result = WordDocumentParser().parse(path)

    assert result.blocks[0].kind is BlockKind.HEADING
    assert result.blocks[0].section_path == ("算法",)
    assert result.blocks[1].section_path == ("算法",)


def test_pptx_parser_uses_presentation_order_and_preserves_slide_numbers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lecture.pptx"
    presentation = """\
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst>
</p:presentation>"""
    relationships = """\
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="slides/slide1.xml" Type="slide"/>
  <Relationship Id="rId2" Target="slides/slide2.xml" Type="slide"/>
</Relationships>"""
    slide_two = _slide_xml(
        "线性表",
        body="数组",
        bullet=True,
        include_table=True,
        include_picture=True,
    )
    slide_one = _slide_xml("课程总结", body="复杂度分析")
    _write_package(
        path,
        {
            "[Content_Types].xml": _content_types(),
            "ppt/presentation.xml": presentation,
            "ppt/_rels/presentation.xml.rels": relationships,
            "ppt/slides/slide1.xml": slide_one,
            "ppt/slides/slide2.xml": slide_two,
        },
    )

    result = PowerPointParser().parse(path)

    assert result.parser_name == "pptx-ooxml-v1"
    assert [block.text for block in result.blocks] == [
        "线性表",
        "数组",
        "操作 | 复杂度",
        "[图片 1：链表示意图]",
        "课程总结",
        "复杂度分析",
    ]
    assert [block.kind for block in result.blocks[:4]] == [
        BlockKind.HEADING,
        BlockKind.LIST,
        BlockKind.TABLE,
        BlockKind.IMAGE,
    ]
    assert [block.source.slide_number for block in result.blocks] == [1, 1, 1, 1, 2, 2]
    assert result.blocks[3].section_path == ("线性表",)
    assert result.blocks[-1].section_path == ("课程总结",)


def test_pptx_parser_warns_for_empty_slides(tmp_path: Path) -> None:
    path = tmp_path / "empty-slide.pptx"
    _write_pptx(path, [_slide_xml(None), _slide_xml("有内容")])

    result = PowerPointParser().parse(path)

    assert [warning.code for warning in result.warnings] == ["EMPTY_SLIDE"]
    assert result.warnings[0].slide_number == 1
    assert result.blocks[0].source.slide_number == 2


def test_pptx_parser_infers_a_heading_when_title_placeholder_is_absent(
    tmp_path: Path,
) -> None:
    path = tmp_path / "custom-title.pptx"
    slide = """\
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>
<p:sp><p:nvSpPr><p:cNvPr id="2" name="Rectangle 2"/><p:cNvSpPr/><p:nvPr/>
</p:nvSpPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>自定义封面</a:t>
</a:r></a:p></p:txBody></p:sp>
</p:spTree></p:cSld></p:sld>"""
    _write_pptx(path, [slide])

    result = PowerPointParser().parse(path)

    assert result.blocks[0].kind is BlockKind.HEADING
    assert result.blocks[0].section_path == ("自定义封面",)


@pytest.mark.parametrize("parser_type", [WordDocumentParser, PowerPointParser])
def test_office_parsers_reject_non_zip_files(
    tmp_path: Path,
    parser_type: type[WordDocumentParser] | type[PowerPointParser],
) -> None:
    path = tmp_path / f"broken.{next(iter(parser_type.file_types))}"
    path.write_bytes(b"not a zip")

    with pytest.raises(InvalidDocumentFormatError):
        parser_type().parse(path)


def test_office_parsers_reject_packages_without_readable_content(
    tmp_path: Path,
) -> None:
    docx_path = tmp_path / "blank.docx"
    _write_package(
        docx_path,
        {
            "[Content_Types].xml": _content_types(),
            "word/document.xml": (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body/></w:document>'
            ),
        },
    )

    with pytest.raises(EmptyDocumentError):
        WordDocumentParser().parse(docx_path)


def test_default_registry_routes_office_types_case_insensitively(
    tmp_path: Path,
) -> None:
    path = tmp_path / "LECTURE.PPTX"
    _write_pptx(path, [_slide_xml("标题")])

    result = build_default_registry().parse(path)

    assert result.file_type == "pptx"
    assert result.blocks[0].text == "标题"


def _write_pptx(path: Path, slides: list[str]) -> None:
    slide_ids = "".join(
        f'<p:sldId id="{256 + index}" r:id="rId{index + 1}"/>'
        for index in range(len(slides))
    )
    relationships = "".join(
        f'<Relationship Id="rId{index + 1}" Target="slides/slide{index + 1}.xml" Type="slide"/>'
        for index in range(len(slides))
    )
    members = {
        "[Content_Types].xml": _content_types(),
        "ppt/presentation.xml": (
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/'
            'presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships"><p:sldIdLst>{slide_ids}'
            "</p:sldIdLst></p:presentation>"
        ),
        "ppt/_rels/presentation.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            f'2006/relationships">{relationships}</Relationships>'
        ),
    }
    members.update(
        {f"ppt/slides/slide{index + 1}.xml": slide for index, slide in enumerate(slides)}
    )
    _write_package(path, members)


def _slide_xml(
    title: str | None,
    *,
    body: str | None = None,
    bullet: bool = False,
    include_table: bool = False,
    include_picture: bool = False,
) -> str:
    title_shape = ""
    if title is not None:
        title_shape = f"""\
<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/>
<p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>"""
    body_shape = ""
    if body is not None:
        paragraph_properties = "<a:pPr><a:buChar char=\"•\"/></a:pPr>" if bullet else ""
        body_shape = f"""\
<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr/>
<p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>
<p:txBody><a:bodyPr/><a:lstStyle/><a:p>{paragraph_properties}<a:r><a:t>{body}</a:t></a:r></a:p></p:txBody></p:sp>"""
    table = ""
    if include_table:
        table = """\
<p:graphicFrame><p:nvGraphicFramePr/><p:xfrm/><a:graphic><a:graphicData><a:tbl>
<a:tr h="1"><a:tc><a:txBody><a:bodyPr/><a:lstStyle/>
<a:p><a:r><a:t>操作</a:t></a:r></a:p></a:txBody></a:tc>
<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>复杂度</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
</a:tbl></a:graphicData></a:graphic></p:graphicFrame>"""
    picture = ""
    if include_picture:
        picture = """\
<p:pic><p:nvPicPr><p:cNvPr id="5" name="Picture 1" descr="链表示意图"/>
<p:cNvPicPr/><p:nvPr/></p:nvPicPr></p:pic>"""
    return f"""\
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>{title_shape}{body_shape}{table}{picture}</p:spTree></p:cSld>
</p:sld>"""
