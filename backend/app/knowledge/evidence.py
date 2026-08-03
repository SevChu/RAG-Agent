from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.knowledge.models import VectorSearchResult


class ContentRole(StrEnum):
    """The factual role a chunk may play in a grounded answer."""

    EXPOSITION = "exposition"
    EXAMPLE = "example"
    EXERCISE_QUESTION = "exercise_question"
    EXERCISE_ANSWER = "exercise_answer"
    CODE = "code"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    role: ContentRole
    eligible: bool
    reason: str | None = None


_ANSWER_HEADING = re.compile(r"(?:参考)?答案|解析|题解|解答")
_EXAMPLE_HEADING = re.compile(r"(?:^|[/\s])例(?:题|\s*\d+)|示例|实例")
_EXERCISE_HEADING = re.compile(
    r"习题|练习|复习题|思考题|测试题|自测|选择题|判断题|填空题"
)
_OPTION_LINE = re.compile(r"(?:^|\n)\s*[A-FＡ-Ｆ][.．、:)）]\s*", re.MULTILINE)
_QUESTION_CUE = re.compile(
    r"下列.{0,24}(?:正确|错误|不正确|不属于|属于)|"
    r"(?:正确|错误)的是|请选择|判断.{0,8}(?:正误|对错)|"
    r"在\s*[（(]\s*[）)]\s*中"
)
_NUMBERED_QUESTION = re.compile(
    r"(?:^|\n)\s*(?:\d+[.、]|[（(]\d+[）)])[^\n]{0,120}[？?（(]",
    re.MULTILINE,
)
_SHORT_NUMBERED_ITEM = re.compile(r"^\s*#?\s*\d{1,2}[.、](?!\d)\s*")
_NUMBERED_ITEMS = re.compile(r"(?:^|[\n。；])\s*#?\s*\d{1,2}[.、](?!\d)\s*")


def classify_content_role(text: str, payload: dict[str, Any]) -> ContentRole:
    """Classify a chunk conservatively without calling an LLM."""

    stored_role = payload.get("content_role")
    if isinstance(stored_role, str):
        try:
            return ContentRole(stored_role)
        except ValueError:
            pass

    normalized_text = text.strip()
    if not normalized_text:
        return ContentRole.UNKNOWN
    block_kinds = {
        str(value).strip().lower() for value in payload.get("block_kinds", [])
    }
    if "code" in block_kinds:
        return ContentRole.CODE

    section_path = " / ".join(
        str(value).strip() for value in payload.get("section_path", [])
    )
    heading_and_prefix = f"{section_path}\n{normalized_text[:240]}"
    if _ANSWER_HEADING.search(heading_and_prefix):
        return ContentRole.EXERCISE_ANSWER
    if _EXAMPLE_HEADING.search(heading_and_prefix):
        return ContentRole.EXAMPLE

    option_count = len(_OPTION_LINE.findall(normalized_text))
    question_mark_count = normalized_text.count("？") + normalized_text.count("?")
    short_numbered_item = bool(
        len(normalized_text) <= 260 and _SHORT_NUMBERED_ITEM.search(normalized_text)
    )
    multiple_numbered_items = len(_NUMBERED_ITEMS.findall(normalized_text)) >= 2
    looks_like_question = bool(
        _EXERCISE_HEADING.search(section_path)
        or option_count >= 2
        or _QUESTION_CUE.search(normalized_text)
        or _NUMBERED_QUESTION.search(normalized_text)
        or question_mark_count >= 2
        or short_numbered_item
        or multiple_numbered_items
    )
    if looks_like_question:
        return ContentRole.EXERCISE_QUESTION
    return ContentRole.EXPOSITION


def assess_evidence(result: VectorSearchResult) -> EvidenceAssessment:
    """Separate topical relevance from permission to support factual claims."""

    role = classify_content_role(result.text, result.payload)
    if role is ContentRole.EXERCISE_QUESTION:
        return EvidenceAssessment(
            role=role,
            eligible=False,
            reason="未作答题干或选项只能定义任务，不能证明事实结论。",
        )
    if role is ContentRole.UNKNOWN:
        return EvidenceAssessment(
            role=role,
            eligible=False,
            reason="内容角色无法可靠识别，未自动授予事实证据资格。",
        )
    return EvidenceAssessment(role=role, eligible=True)
