from __future__ import annotations

import pytest

from app.core.exceptions import LLMOutputError
from app.generation import (
    AnswerStatus,
    AnswerStyle,
    ChatCompletion,
    GroundedAnswerGenerator,
    TokenUsage,
)
from app.knowledge import VectorSearchResult


class FakeGateway:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, str]] = []

    async def complete(self, *, system_prompt: str, user_prompt: str) -> ChatCompletion:
        self.calls.append((system_prompt, user_prompt))
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
    )

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.used_source_ids == (1,)
    assert answer.model == "test-model"
    assert answer.usage is not None and answer.usage.total_tokens == 120
    assert eligible == (_hit(),)
    assert "只允许使用" in gateway.calls[0][0]
    assert "数据结构讲义.md" in gateway.calls[0][1]


async def test_grounded_answer_refuses_without_eligible_evidence_or_llm_call() -> None:
    gateway = FakeGateway("this response must never be used")
    generator = GroundedAnswerGenerator(gateway, min_similarity_score=0.5)

    answer, eligible = await generator.answer(
        question="课程资料之外的问题",
        hits=[_hit(score=0.2)],
        style=AnswerStyle.CONCISE,
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

    await generator.answer(question="什么是栈？", hits=[_hit()], style=style)

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
        '{"sufficient_evidence":true,"answer":"正文引用。[1]",'
        '"used_source_ids":[]}',
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
        )
