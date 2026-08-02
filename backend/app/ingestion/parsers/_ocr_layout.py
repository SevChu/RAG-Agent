from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median

from app.ingestion.models import BlockKind

_TABLE_TITLE_RE = re.compile(r"^表\s*\d+(?:\s*[-－]\s*\d+)?")
_CODE_START_RE = re.compile(
    r"^(?:class|struct|template|public:|protected:|private:|bool\b|void\b|int\b|"
    r"float\b|double\b|char\b|Status\b|SeqList\b|if\s*\(|for\s*\(|while\s*\(|"
    r"return\b|else\b|#include\b|using\b|[{}])"
)
_CODE_CONTINUATION_RE = re.compile(
    r"^(?://|/\*|\*|[{}];?$|\};?$|\|\||&&|[A-Za-z_]\w*(?:<[^>]+>)?\s*[:=(])"
)
_NUMBERED_HEADING_RE = re.compile(
    r"^(?:\d{1,3}(?:\.\d{1,3})*\.\s+\S|"
    r"[一二三四五六七八九十百]+、\s*[A-Za-z\u3400-\u9fff])"
)


@dataclass(frozen=True, slots=True)
class LayoutLine:
    text: str
    confidence: float
    box: tuple[float, float, float, float]

    @property
    def left(self) -> float:
        return self.box[0]

    @property
    def top(self) -> float:
        return self.box[1]

    @property
    def right(self) -> float:
        return self.box[2]

    @property
    def bottom(self) -> float:
        return self.box[3]

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True, slots=True)
class OcrLayoutBlock:
    kind: BlockKind
    text: str
    confidence: float
    top: float


@dataclass(frozen=True, slots=True)
class _TableRegion:
    block: OcrLayoutBlock
    line_ids: frozenset[int]
    top: float
    bottom: float
    interrupts_prose: bool


class OcrLayoutAnalyzer:
    """Reconstruct basic paragraphs, tables and code from positioned OCR lines."""

    def analyze(
        self,
        lines: tuple[LayoutLine, ...],
        *,
        page_width: int,
        page_height: int,
    ) -> tuple[OcrLayoutBlock, ...]:
        if not lines:
            return ()
        ordered = tuple(
            sorted(
                (
                    line
                    for line in lines
                    if line.bottom > page_height * 0.11
                    and line.top < page_height * 0.96
                ),
                key=lambda line: (line.top, line.left),
            )
        )
        if not ordered:
            return ()
        line_height = median(max(1.0, line.height) for line in ordered)
        tables = self._table_regions(
            ordered,
            page_width=page_width,
            line_height=line_height,
        )
        table_line_ids = {line_id for table in tables for line_id in table.line_ids}
        remaining = tuple(
            line for line in ordered if id(line) not in table_line_ids
        )
        code_blocks, prose_lines = self._code_blocks(remaining, line_height=line_height)
        prose_blocks = self._paragraph_blocks(
            prose_lines,
            page_width=page_width,
            line_height=line_height,
            table_regions=tables,
        )
        blocks = [*(table.block for table in tables), *code_blocks, *prose_blocks]
        return tuple(sorted(blocks, key=lambda block: block.top))

    def _table_regions(
        self,
        lines: tuple[LayoutLine, ...],
        *,
        page_width: int,
        line_height: float,
    ) -> tuple[_TableRegion, ...]:
        regions: list[_TableRegion] = []
        already_used: set[int] = set()
        for title in lines:
            if id(title) in already_used or not _TABLE_TITLE_RE.match(title.text):
                continue
            concurrent_left = [
                line
                for line in lines
                if line is not title
                and self._same_row(line, title, line_height)
                and line.right < title.left - line_height
            ]
            if concurrent_left:
                left_edge = (max(line.right for line in concurrent_left) + title.left) / 2
                right_edge = page_width * 0.95
                right_side = True
            else:
                left_edge = page_width * 0.07
                right_edge = page_width * 0.93
                right_side = False

            candidates = [
                line
                for line in lines
                if id(line) not in already_used
                and line.top >= title.top - line_height * 0.25
                and line.left >= left_edge
                and line.right <= right_edge
            ]
            rows = self._rows(candidates, line_height=line_height)
            selected_rows: list[tuple[LayoutLine, ...]] = []
            dense_rows = 0
            previous_bottom = title.bottom
            for row in rows:
                if not row or row[0].top < title.top - line_height * 0.25:
                    continue
                if selected_rows and row[0].top - previous_bottom > line_height * 1.9:
                    break
                if (
                    not right_side
                    and dense_rows >= 2
                    and len(row) == 1
                    and row[0].width >= page_width * 0.65
                    and row[0] is not title
                ):
                    break
                selected_rows.append(row)
                if len(row) >= 2:
                    dense_rows += 1
                previous_bottom = max(line.bottom for line in row)

            selected = tuple(line for row in selected_rows for line in row)
            if title not in selected or len(selected) < 3 or dense_rows < 1:
                continue
            row_texts = [
                " | ".join(line.text for line in sorted(row, key=lambda item: item.left))
                for row in selected_rows
            ]
            region = _TableRegion(
                block=OcrLayoutBlock(
                    kind=BlockKind.TABLE,
                    text="\n".join(row_texts),
                    confidence=min(line.confidence for line in selected),
                    top=min(line.top for line in selected),
                ),
                line_ids=frozenset(id(line) for line in selected),
                top=min(line.top for line in selected),
                bottom=max(line.bottom for line in selected),
                interrupts_prose=not right_side,
            )
            regions.append(region)
            already_used.update(region.line_ids)
        return tuple(regions)

    def _code_blocks(
        self,
        lines: tuple[LayoutLine, ...],
        *,
        line_height: float,
    ) -> tuple[tuple[OcrLayoutBlock, ...], tuple[LayoutLine, ...]]:
        blocks: list[OcrLayoutBlock] = []
        prose: list[LayoutLine] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if (
                _is_formula_line(line.text)
                and not _is_strong_code_start(line.text)
            ) or not _is_code_line(line.text):
                prose.append(line)
                index += 1
                continue
            code_lines = [line]
            index += 1
            while index < len(lines):
                candidate = lines[index]
                gap = candidate.top - code_lines[-1].bottom
                if (
                    gap > line_height * 1.6
                    or not _is_code_line(candidate.text)
                ):
                    break
                code_lines.append(candidate)
                index += 1
            if len(code_lines) == 1 and not _is_strong_code_start(code_lines[0].text):
                prose.extend(code_lines)
                continue
            blocks.append(
                OcrLayoutBlock(
                    kind=BlockKind.CODE,
                    text="\n".join(item.text for item in code_lines),
                    confidence=min(item.confidence for item in code_lines),
                    top=code_lines[0].top,
                )
            )
        return tuple(blocks), tuple(prose)

    def _paragraph_blocks(
        self,
        lines: tuple[LayoutLine, ...],
        *,
        page_width: int,
        line_height: float,
        table_regions: tuple[_TableRegion, ...],
    ) -> tuple[OcrLayoutBlock, ...]:
        if not lines:
            return ()
        left_margin = median(line.left for line in lines)
        indent_threshold = max(line_height * 1.25, page_width * 0.03)
        paragraphs: list[list[LayoutLine]] = []
        current: list[LayoutLine] = []
        for line in lines:
            if current and self._paragraph_break(
                previous=current[-1],
                current=line,
                left_margin=left_margin,
                indent_threshold=indent_threshold,
                line_height=line_height,
                table_regions=table_regions,
            ):
                paragraphs.append(current)
                current = []
            current.append(line)
        if current:
            paragraphs.append(current)
        return tuple(
            OcrLayoutBlock(
                kind=_paragraph_kind(paragraph),
                text=(
                    "\n".join(line.text for line in paragraph)
                    if all(_is_formula_line(line.text) for line in paragraph)
                    else _join_prose(paragraph)
                ),
                confidence=min(line.confidence for line in paragraph),
                top=paragraph[0].top,
            )
            for paragraph in paragraphs
        )

    @staticmethod
    def _paragraph_break(
        *,
        previous: LayoutLine,
        current: LayoutLine,
        left_margin: float,
        indent_threshold: float,
        line_height: float,
        table_regions: tuple[_TableRegion, ...],
    ) -> bool:
        if _is_formula_line(previous.text) != _is_formula_line(current.text):
            return True
        if _is_numbered_heading(previous.text) or _is_numbered_heading(current.text):
            return True
        if current.top - previous.bottom > line_height * 1.35:
            return True
        if (
            current.left - left_margin >= indent_threshold
            and previous.left - left_margin < indent_threshold
        ):
            return True
        return any(
            table.interrupts_prose
            and previous.center_y <= table.bottom < current.center_y
            for table in table_regions
        )

    @staticmethod
    def _same_row(first: LayoutLine, second: LayoutLine, line_height: float) -> bool:
        return abs(first.center_y - second.center_y) <= line_height * 0.65

    @classmethod
    def _rows(
        cls,
        lines: list[LayoutLine],
        *,
        line_height: float,
    ) -> tuple[tuple[LayoutLine, ...], ...]:
        rows: list[list[LayoutLine]] = []
        for line in sorted(lines, key=lambda item: (item.center_y, item.left)):
            if not rows or not cls._same_row(rows[-1][0], line, line_height):
                rows.append([line])
            else:
                rows[-1].append(line)
        return tuple(tuple(sorted(row, key=lambda item: item.left)) for row in rows)


def _is_strong_code_start(text: str) -> bool:
    return bool(_CODE_START_RE.match(text.strip()))


def _is_numbered_heading(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) <= 80 and bool(_NUMBERED_HEADING_RE.match(stripped))


def _paragraph_kind(lines: list[LayoutLine]) -> BlockKind:
    if len(lines) == 1 and _is_numbered_heading(lines[0].text):
        return BlockKind.HEADING
    if all(_is_formula_line(line.text) for line in lines):
        return BlockKind.FORMULA
    return BlockKind.PARAGRAPH


def _is_code_line(text: str) -> bool:
    stripped = text.strip()
    if _CODE_START_RE.match(stripped) or _CODE_CONTINUATION_RE.match(stripped):
        return True
    if stripped.endswith(";") and re.search(r"[A-Za-z_]", stripped):
        return True
    return False


def _is_formula_line(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 100 or not re.search(r"[=+*/^<>≤≥∑√]", stripped):
        return False
    formula_characters = sum(
        character.isdigit() or character in "=+-*/^()[]{}<>≤≥∑√., "
        for character in stripped
    )
    return formula_characters / max(1, len(stripped)) >= 0.45


def _join_prose(lines: list[LayoutLine]) -> str:
    text = lines[0].text
    for line in lines[1:]:
        separator = (
            " "
            if text[-1:].isascii()
            and text[-1:].isalnum()
            and line.text[:1].isascii()
            and line.text[:1].isalnum()
            else ""
        )
        text += separator + line.text
    return text
