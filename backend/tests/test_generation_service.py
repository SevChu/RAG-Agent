from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.core.exceptions import LLMOutputError
from app.external_search import ExternalSearchEvidence, ExternalSourceQuality
from app.generation import (
    AnswerStatus,
    AnswerStyle,
    ChatCompletion,
    GroundedAnswerGenerator,
    MixedGroundedAnswerGenerator,
    TokenUsage,
)
from app.knowledge import VectorSearchResult


class FakeGateway:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, str, str]] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        self.calls.append((system_prompt, user_prompt, model))
        return ChatCompletion(
            content=self.content,
            model="test-model",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        )


def _hit(*, score: float = 0.88) -> VectorSearchResult:
    return VectorSearchResult(
        point_id="point-1",
        score=score,
        course_id="course-1",
        document_id="6ed47978-b1c5-4d3e-9f79-d7d35c0477bd",
        chunk_index=2,
        text="栈是一种后进先出的线性表。",
        payload={
            "file_name": "数据结构讲义.md",
            "section_path": ["栈"],
            "page_numbers": [],
            "slide_numbers": [],
            "line_start": 8,
            "line_end": 10,
            "block_kinds": ["paragraph"],
        },
    )


def _external_evidence() -> ExternalSearchEvidence:
    return ExternalSearchEvidence(
        rank=1,
        title="Python 3.14 documentation",
        publisher="Python Software Foundation",
        url="https://docs.python.org/3.14/",
        accessed_at=datetime(2026, 8, 4, tzinfo=UTC),
        evidence_excerpt="Python 3.14 是当前文档版本。",
        quality=ExternalSourceQuality.OFFICIAL,
    )


async def test_grounded_answer_accepts_only_declared_inline_citations() -> None:
    gateway = FakeGateway(
        '{"sufficient_evidence":true,"answer":"栈遵循后进先出原则。[1]",'
        '"used_source_ids":[1]}'
    )
    generator = GroundedAnswerGenerator(gateway, min_similarity_score=0.3)

    answer, eligible = await generator.answer(
        question="什么是栈？",
        hits=[_hit()],
        style=AnswerStyle.BALANCED,
        model="deepseek-v4-pro",
    )

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.used_source_ids == (1,)
    assert answer.model == "test-model"
    assert answer.usage is not None and answer.usage.total_tokens == 120
    assert eligible == (_hit(),)
    assert "只允许使用" in gateway.calls[0][0]
    assert "数据结构讲义.md" in gateway.calls[0][1]
    assert gateway.calls[0][2] == "deepseek-v4-pro"


async def test_grounded_answer_refuses_without_eligible_evidence_or_llm_call() -> None:
    gateway = FakeGateway("this response must never be used")
    generator = GroundedAnswerGenerator(gateway, min_similarity_score=0.5)

    answer, eligible = await generator.answer(
        question="课程资料之外的问题",
        hits=[_hit(score=0.2)],
        style=AnswerStyle.CONCISE,
        model="deepseek-v4-flash",
    )

    assert answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert answer.used_source_ids == ()
    assert answer.model is None
    assert eligible == ()
    assert gateway.calls == []


@pytest.mark.parametrize(
    ("style", "required_markers", "forbidden_markers"),
    [
        (
            AnswerStyle.CONCISE,
            ("80～160", "不使用标题", "最多 3 个单句短要点"),
            ("## 结论", "## 推导与延伸"),
        ),
        (
            AnswerStyle.BALANCED,
            ("220～450", "## 结论", "## 关键要点", "2～4 条"),
            ("## 推导与延伸",),
        ),
        (
            AnswerStyle.DETAILED,
            (
                "500～900",
                "## 资料依据",
                "## 推导与延伸",
                "证据前提 → 推理过程 → 可得结论/应用",
                "基于资料的推导",
            ),
            ("不使用标题",),
        ),
    ],
)
async def test_answer_styles_use_distinct_output_contracts(
    style: AnswerStyle,
    required_markers: tuple[str, ...],
    forbidden_markers: tuple[str, ...],
) -> None:
    gateway = FakeGateway(
        '{"sufficient_evidence":true,"answer":"栈遵循后进先出原则。[1]",'
        '"used_source_ids":[1]}'
    )
    generator = GroundedAnswerGenerator(gateway, min_similarity_score=0.3)

    await generator.answer(
        question="什么是栈？",
        hits=[_hit()],
        style=style,
        model="deepseek-v4-flash",
    )

    system_prompt = gateway.calls[0][0]
    for marker in required_markers:
        assert marker in system_prompt
    for marker in forbidden_markers:
        assert marker not in system_prompt


@pytest.mark.parametrize(
    "content",
    [
        '{"sufficient_evidence":true,"answer":"错误引用。[2]",'
        '"used_source_ids":[2]}',
        '{"sufficient_evidence":true,"answer":"没有引用",'
        '"used_source_ids":[]}',
        "not-json",
    ],
)
async def test_grounded_answer_blocks_invalid_model_citations(content: str) -> None:
    generator = GroundedAnswerGenerator(FakeGateway(content), min_similarity_score=0.3)

    with pytest.raises(LLMOutputError):
        await generator.answer(
            question="什么是栈？",
            hits=[_hit()],
            style=AnswerStyle.DETAILED,
            model="deepseek-v4-flash",
        )


@pytest.mark.parametrize(
    ("answer_text", "declared_ids", "expected_ids"),
    [
        ("先看第二条。[2] 再看第一条。[1]", [1, 2], (2, 1)),
        ("两条资料共同支持。[1, 2]", [2, 1], (1, 2)),
        ("两条资料共同支持。[1，2]", [], (1, 2)),
        ("两条资料共同支持。[1、2]", [1, 1, 2], (1, 2)),
        ("重复引用第一条。[1] 再次引用。[1]", [1], (1,)),
    ],
)
async def test_grounded_answer_uses_visible_citations_as_source_of_truth(
    answer_text: str,
    declared_ids: list[int],
    expected_ids: tuple[int, ...],
) -> None:
    second_hit = VectorSearchResult(
        point_id="point-2",
        score=0.82,
        course_id="course-1",
        document_id="3f9d3698-504c-4aed-8f80-8422126b8810",
        chunk_index=5,
        text="队列是一种先进先出的线性表。",
        payload={"file_name": "数据结构讲义.md"},
    )
    gateway = FakeGateway(
        '{"sufficient_evidence":true,'
        f'"answer":{json.dumps(answer_text, ensure_ascii=False)},'
        f'"used_source_ids":{json.dumps(declared_ids)}'
        "}"
    )
    generator = GroundedAnswerGenerator(gateway, min_similarity_score=0.3)

    answer, _ = await generator.answer(
        question="比较栈和队列。",
        hits=[_hit(), second_hit],
        style=AnswerStyle.BALANCED,
        model="deepseek-v4-flash",
    )

    assert answer.used_source_ids == expected_ids


async def test_mixed_answer_validates_course_and_external_namespaces() -> None:
    gateway = FakeGateway(
        '{"sufficient_evidence":true,'
        '"answer":"课程解释栈的定义。[课1] 官方文档补充当前版本。[外1]",'
        '"used_course_source_ids":[1],"used_external_source_ids":[1],'
        '"has_source_conflict":false}'
    )
    generator = MixedGroundedAnswerGenerator(gateway, min_similarity_score=0.3)

    answer, eligible = await generator.answer(
        question="解释栈并补充当前资料",
        standalone_question="解释栈并补充当前资料",
        course_hits=[_hit()],
        external_evidence=[_external_evidence()],
        style=AnswerStyle.BALANCED,
        model="deepseek-v4-flash",
    )

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.used_source_ids == (1,)
    assert answer.used_external_source_ids == (1,)
    assert eligible == (_hit(),)
    assert "[课n]" in gateway.calls[0][0]
    assert "[外n]" in gateway.calls[0][0]
    assert "docs.python.org" in gateway.calls[0][1]


@pytest.mark.parametrize(
    "answer_text",
    [
        "混合回答不能使用模糊编号。[1]",
        "外部编号不存在。[外2]",
        "课程编号不存在。[课2]",
    ],
)
async def test_mixed_answer_blocks_invalid_namespaced_citations(
    answer_text: str,
) -> None:
    gateway = FakeGateway(
        '{"sufficient_evidence":true,'
        f'"answer":{json.dumps(answer_text, ensure_ascii=False)},'
        '"used_course_source_ids":[],"used_external_source_ids":[],'
        '"has_source_conflict":false}'
    )
    generator = MixedGroundedAnswerGenerator(gateway, min_similarity_score=0.3)

    with pytest.raises(LLMOutputError):
        await generator.answer(
            question="混合问题",
            standalone_question="混合问题",
            course_hits=[_hit()],
            external_evidence=[_external_evidence()],
            style=AnswerStyle.BALANCED,
            model="deepseek-v4-flash",
        )


async def test_mixed_answer_requires_parallel_conflict_display() -> None:
    conflict_answer = "## 资料差异\n课程采用旧版本。[课1] 外部文档说明新版本。[外1]"
    gateway = FakeGateway(
        '{"sufficient_evidence":true,'
        f'"answer":{json.dumps(conflict_answer, ensure_ascii=False)},'
        '"used_course_source_ids":[1],"used_external_source_ids":[1],'
        '"has_source_conflict":true}'
    )
    generator = MixedGroundedAnswerGenerator(gateway, min_similarity_score=0.3)

    answer, _ = await generator.answer(
        question="课程与当前文档是否一致？",
        standalone_question="课程与当前文档是否一致？",
        course_hits=[_hit()],
        external_evidence=[_external_evidence()],
        style=AnswerStyle.DETAILED,
        model="deepseek-v4-flash",
    )

    assert answer.has_source_conflict is True
    assert "## 资料差异" in answer.answer
