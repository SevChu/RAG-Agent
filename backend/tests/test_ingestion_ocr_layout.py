from app.ingestion.models import BlockKind
from app.ingestion.parsers._ocr_layout import LayoutLine, OcrLayoutAnalyzer


def _line(
    text: str,
    left: float,
    top: float,
    right: float,
    bottom: float,
    confidence: float = 0.95,
) -> LayoutLine:
    return LayoutLine(
        text=text,
        confidence=confidence,
        box=(left, top, right, bottom),
    )


def test_layout_reconstructs_indented_chinese_paragraphs_and_drops_header() -> None:
    lines = (
        _line("数据结构——C++实现", 180, 40, 500, 70),
        _line("第一段第一行，说明虚函数的用途。", 100, 150, 800, 180),
        _line("第一段第二行，语义应继续。", 100, 190, 650, 220),
        _line("第二段首行具有缩进。", 150, 250, 650, 280),
        _line("第二段第二行不能被当成新段。", 100, 290, 800, 320),
    )

    blocks = OcrLayoutAnalyzer().analyze(lines, page_width=1000, page_height=1000)

    assert [(block.kind, block.text) for block in blocks] == [
        (
            BlockKind.PARAGRAPH,
            "第一段第一行，说明虚函数的用途。第一段第二行，语义应继续。",
        ),
        (
            BlockKind.PARAGRAPH,
            "第二段首行具有缩进。第二段第二行不能被当成新段。",
        ),
    ]


def test_layout_separates_right_side_table_from_left_prose() -> None:
    lines = (
        _line("正文第一行，介绍计算过程。", 100, 150, 550, 180),
        _line("表4-1 后缀表达式的计算过程", 650, 155, 930, 185),
        _line("正文第二行继续说明。", 100, 190, 550, 220),
        _line("操作", 650, 200, 720, 230),
        _line("后缀表达式", 800, 200, 930, 230),
        _line("32 - 26", 650, 240, 720, 270),
        _line("6 5 *", 800, 240, 900, 270),
        _line("30 + 7", 650, 280, 720, 310),
        _line("37", 800, 280, 840, 310),
        _line("表后正文恢复整行，不应并入表格。", 100, 340, 900, 370),
    )

    blocks = OcrLayoutAnalyzer().analyze(lines, page_width=1000, page_height=1000)

    assert [block.kind for block in blocks] == [
        BlockKind.PARAGRAPH,
        BlockKind.TABLE,
        BlockKind.PARAGRAPH,
    ]
    assert blocks[0].text == "正文第一行，介绍计算过程。正文第二行继续说明。"
    assert blocks[1].text == (
        "表4-1 后缀表达式的计算过程\n"
        "操作 | 后缀表达式\n"
        "32 - 26 | 6 5 *\n"
        "30 + 7 | 37"
    )
    assert blocks[2].text == "表后正文恢复整行，不应并入表格。"


def test_layout_protects_full_width_table_multiline_formula_and_code() -> None:
    lines = (
        _line("表4-2 计算步骤", 350, 150, 650, 180),
        _line("步", 100, 200, 150, 230),
        _line("操作", 300, 200, 400, 230),
        _line("栈中内容", 700, 200, 850, 230),
        _line("1", 100, 240, 150, 270),
        _line("32入栈", 300, 240, 430, 270),
        _line("32", 700, 240, 750, 270),
        _line("公式如下：", 100, 330, 350, 360),
        _line("x = a + b", 350, 380, 600, 410),
        _line("y = x / n", 350, 420, 600, 450),
        _line("之后继续解释公式。", 100, 470, 500, 500),
        _line("bool IsOperator(char ch)", 250, 550, 600, 580),
        _line("{", 250, 590, 280, 620),
        _line("return true;", 300, 630, 500, 660),
        _line("}", 250, 670, 280, 700),
    )

    blocks = OcrLayoutAnalyzer().analyze(lines, page_width=1000, page_height=1000)

    assert [block.kind for block in blocks] == [
        BlockKind.TABLE,
        BlockKind.PARAGRAPH,
        BlockKind.FORMULA,
        BlockKind.PARAGRAPH,
        BlockKind.CODE,
    ]
    assert blocks[2].text == "x = a + b\ny = x / n"
    assert blocks[4].text == "bool IsOperator(char ch)\n{\nreturn true;\n}"


def test_layout_keeps_operator_heavy_if_statement_in_code_block() -> None:
    lines = (
        _line("bool IsOperator(char ch)", 250, 150, 600, 180),
        _line("if (ch == '+' || ch == '-' || ch == '*')", 250, 190, 800, 220),
        _line("return true;", 300, 230, 500, 260),
        _line("else", 250, 270, 350, 300),
        _line("return false;", 300, 310, 520, 340),
    )

    blocks = OcrLayoutAnalyzer().analyze(lines, page_width=1000, page_height=1000)

    assert len(blocks) == 1
    assert blocks[0].kind is BlockKind.CODE
    assert "if (ch == '+' || ch == '-' || ch == '*')" in blocks[0].text
