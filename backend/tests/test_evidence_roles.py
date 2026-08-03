from __future__ import annotations

import pytest

from app.knowledge.evidence import ContentRole, assess_evidence, classify_content_role
from app.knowledge.models import VectorSearchResult


@pytest.mark.parametrize(
    ("text", "payload", "expected"),
    [
        (
            "队列只允许在一端插入、另一端删除，遵循先进先出。",
            {"section_path": ["队列的定义"], "block_kinds": ["paragraph"]},
            ContentRole.EXPOSITION,
        ),
        (
            "1. 队列是一种先进后出的线性表（ ）。\n2. 栈可以在两端操作（ ）。",
            {"section_path": ["习题"], "block_kinds": ["paragraph"]},
            ContentRole.EXERCISE_QUESTION,
        ),
        (
            "A. 栈\nB. 队列\nC. 数组\nD. 图",
            {"section_path": [], "block_kinds": ["list"]},
            ContentRole.EXERCISE_QUESTION,
        ),
        (
            "# 5. 队列是一种先进后出的线性表。 6.栈只允许在表头插入和删除。",
            {"section_path": [], "block_kinds": ["paragraph"]},
            ContentRole.EXERCISE_QUESTION,
        ),
        (
            "参考答案：队列遵循先进先出。",
            {"section_path": ["习题解析"], "block_kinds": ["paragraph"]},
            ContentRole.EXERCISE_ANSWER,
        ),
        (
            "# 9.3 哈希表\n处理冲突的方法包括线性探测、二次探测和双散列法。",
            {"section_path": ["哈希表"], "block_kinds": ["paragraph"]},
            ContentRole.EXPOSITION,
        ),
        (
            "邻接表和邻接矩阵空间复杂度？如何查找邻接点？稠密图选哪一种？",
            {"section_path": [], "block_kinds": ["paragraph"]},
            ContentRole.EXERCISE_QUESTION,
        ),
        (
            "int pop() { return data[top--]; }",
            {"section_path": ["栈"], "block_kinds": ["code"]},
            ContentRole.CODE,
        ),
    ],
)
def test_classify_content_role(
    text: str,
    payload: dict[str, object],
    expected: ContentRole,
) -> None:
    assert classify_content_role(text, payload) is expected


def test_unanswered_exercise_is_relevant_but_not_factual_evidence() -> None:
    hit = VectorSearchResult(
        point_id="question-1",
        score=0.97,
        course_id="course-1",
        document_id="document-1",
        chunk_index=1,
        text="下列关于队列的说法中，正确的是（ ）。",
        payload={"section_path": ["选择题"]},
    )

    assessment = assess_evidence(hit)

    assert assessment.role is ContentRole.EXERCISE_QUESTION
    assert assessment.eligible is False
    assert assessment.reason is not None
