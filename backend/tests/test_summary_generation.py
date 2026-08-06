from __future__ import annotations

import json

import pytest

from app.core.exceptions import LLMOutputError
from app.generation import (
    ChatCompletion,
    DynamicSummaryPlanner,
    GroundedSummaryGenerator,
    SummaryPlan,
    SummarySectionPlan,
    TokenUsage,
)
from app.knowledge import VectorSearchResult
from app.orchestration import SummaryScopeType


class SummaryGateway:
    def __init__(self, *contents: str) -> None:
        self.contents = list(contents)
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        self.calls.append((system_prompt, user_prompt))
        assert self.contents
        return ChatCompletion(
            content=self.contents.pop(0),
            model=model,
            usage=TokenUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("summary generation must use JSON completion")


def _hit(index: int) -> VectorSearchResult:
    texts = (
        "栈遵循后进先出原则，插入和删除都在栈顶进行。",
        "队列遵循先进先出原则，入队在队尾而出队在队首。",
    )
    return VectorSearchResult(
        point_id=f"summary-{index}",
        score=0.91 - index / 100,
        course_id="course-1",
        document_id="document-1",
        chunk_index=index,
        text=texts[index - 1],
        payload={
            "file_name": "讲义.md",
            "section_path": ["线性结构", "栈" if index == 1 else "队列"],
        },
    )


def _plan(*, excluded: list[str] | None = None) -> SummaryPlan:
    return SummaryPlan(
        scope=SummaryScopeType.TOPIC,
        scope_description="聚焦栈和队列",
        goal="对比栈和队列的操作约束",
        focuses=["操作端点", "顺序差异"],
        must_exclude=excluded or [],
        output_format="对比说明",
        sections=[
            SummarySectionPlan(
                key="stack_rules",
                title="栈的操作约束",
                purpose="解释栈的操作端点",
                retrieval_query="栈 操作端点 后进先出",
                organization="约束清单",
            ),
            SummarySectionPlan(
                key="queue_rules",
                title="队列的操作约束",
                purpose="解释队列的操作端点并形成对比",
                retrieval_query="队列 操作端点 先进先出",
                organization="对比说明",
            ),
        ],
    )


def _dynamic_payload(
    *, citation_1: str = "[课1]", citation_2: str = "[课2]"
) -> str:
    return json.dumps(
        {
            "sufficient_evidence": True,
            "title": "栈与队列的操作约束",
            "sections": [
                {
                    "key": "stack_rules",
                    "title": "栈的操作约束",
                    "purpose": "解释栈的操作端点",
                    "body": f"- 插入和删除都集中在栈顶，顺序为后进先出。{citation_1}",
                    "used_source_ids": [1],
                    "limitation": None,
                },
                {
                    "key": "queue_rules",
                    "title": "队列的操作约束",
                    "purpose": "解释队列的操作端点并形成对比",
                    "body": f"- 入队位于队尾，出队位于队首，顺序为先进先出。{citation_2}",
                    "used_source_ids": [2],
                    "limitation": None,
                },
            ],
            "review_advice": None,
            "used_source_ids": [1, 2],
        },
        ensure_ascii=False,
    )


async def test_vague_request_uses_stable_default_plan_without_model_call() -> None:
    gateway = SummaryGateway()
    result = await DynamicSummaryPlanner(gateway).plan(
        request="请帮我总结第三章",
        scope=SummaryScopeType.TOPIC,
        scope_description="聚焦第三章",
        model="deepseek-v4-flash",
    )

    assert result.plan.is_default is True
    assert [section.title for section in result.plan.sections] == [
        "核心框架",
        "关键机制与要点",
        "知识联系",
        "边界与易错点",
        "复习重点",
    ]
    assert gateway.calls == []


async def test_explicit_request_builds_open_ended_dynamic_plan() -> None:
    gateway = SummaryGateway(
        json.dumps(
            {
                "goal": "从工程取舍角度解释第三章",
                "focuses": ["缓存友好性"],
                "audience": "准备重构代码的开发者",
                "detail_level": "详细",
                "length": "约 800 字",
                "output_format": "决策清单",
                "must_include": ["选择条件"],
                "must_exclude": ["考试建议"],
                "sections": [
                    {
                        "key": "engineering_tradeoffs",
                        "title": "工程取舍",
                        "purpose": "比较实现方案",
                        "retrieval_query": "第三章 实现 复杂度 性能 取舍",
                        "evidence_budget": 5,
                        "organization": "决策清单",
                        "required_points": [],
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    result = await DynamicSummaryPlanner(gateway).plan(
        request="从工程取舍角度总结第三章，必须包含选择条件，不要考试建议",
        scope=SummaryScopeType.TOPIC,
        scope_description="聚焦第三章",
        model="deepseek-v4-flash",
    )

    assert result.plan.is_default is False
    assert result.plan.focuses == ["缓存友好性"]
    assert result.plan.must_exclude == ["考试建议"]
    required = result.plan.sections[0].required_points
    assert "缓存友好性" in required
    assert "选择条件" in required
    assert "开放文本" in gateway.calls[0][0]


async def test_dynamic_summary_uses_planned_sections_and_verified_references() -> None:
    gateway = SummaryGateway(_dynamic_payload())
    result = await GroundedSummaryGenerator(gateway).summarize(
        request="对比总结栈和队列的操作端点",
        plan=_plan(),
        hits=(_hit(1), _hit(2)),
        section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
        model="deepseek-v4-flash",
    )

    assert result.answer.used_source_ids == (1, 2)
    assert result.quality.passed is True
    assert result.quality.generated_section_count == 2
    assert "## 栈的操作约束" in result.answer.answer
    assert "## 队列的操作约束" in result.answer.answer
    assert "## 核心概念" not in result.answer.answer
    assert "- [课1] 讲义.md · 线性结构 › 栈" in result.answer.answer
    assert "- [课2] 讲义.md · 线性结构 › 队列" in result.answer.answer
    assert "preferred_source_ids" in gateway.calls[0][1]


async def test_dynamic_summary_rejects_unsafe_citations() -> None:
    for citation_1 in ("[外1]",):
        payload = json.loads(_dynamic_payload(citation_1=citation_1))
        with pytest.raises(LLMOutputError):
            await GroundedSummaryGenerator(
                SummaryGateway(json.dumps(payload, ensure_ascii=False))
            ).summarize(
                request="对比总结栈和队列",
                plan=_plan(),
                hits=(_hit(1), _hit(2)),
                section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
                model="deepseek-v4-flash",
            )


async def test_dynamic_summary_normalizes_course_citation_namespace() -> None:
    payload = json.loads(_dynamic_payload(citation_1="[1]"))
    result = await GroundedSummaryGenerator(
        SummaryGateway(json.dumps(payload, ensure_ascii=False))
    ).summarize(
        request="只用反例和错误做法总结指针",
        plan=_plan(),
        hits=(_hit(1), _hit(2)),
        section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
        model="deepseek-v4-flash",
    )

    assert "[课1]" in result.answer.answer
    assert result.quality.normalized_citation_namespaces == ["stack_rules"]


async def test_invalid_summary_json_retries_with_compact_contract() -> None:
    gateway = SummaryGateway("truncated output", _dynamic_payload())
    result = await GroundedSummaryGenerator(gateway).summarize(
        request="从工程取舍角度总结哈希表",
        plan=_plan(),
        hits=(_hit(1), _hit(2)),
        section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
        model="deepseek-v4-flash",
    )

    assert result.quality.passed is True
    assert len(gateway.calls) == 2
    assert "上一次输出无法解析" in gateway.calls[1][0]


async def test_uncited_section_degrades_locally_instead_of_failing_summary() -> None:
    payload = json.loads(_dynamic_payload())
    payload["sections"][0]["body"] = "这里是没有引用的模型正文。"
    payload["sections"][0]["used_source_ids"] = []
    result = await GroundedSummaryGenerator(
        SummaryGateway(json.dumps(payload, ensure_ascii=False))
    ).summarize(
        request="总结动态规划，但排除公式和代码",
        plan=_plan(),
        hits=(_hit(1), _hit(2)),
        section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
        model="deepseek-v4-flash",
    )

    assert result.answer.status.value == "answered"
    assert result.quality.grounding_fallback_sections == ["stack_rules"]
    assert "本节没有返回有效课程引用" in result.answer.answer


async def test_dynamic_summary_allows_safe_cross_section_course_evidence() -> None:
    payload = json.loads(_dynamic_payload(citation_1="[课2]"))
    payload["sections"][0]["used_source_ids"] = [2]
    result = await GroundedSummaryGenerator(
        SummaryGateway(json.dumps(payload, ensure_ascii=False))
    ).summarize(
        request="对比总结栈和队列",
        plan=_plan(),
        hits=(_hit(1), _hit(2)),
        section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
        model="deepseek-v4-flash",
    )

    assert result.answer.used_source_ids == (2,)
    assert result.quality.cross_section_evidence_reuse == ["stack_rules: [课2]"]
    assert result.quality.passed is True


async def test_body_citations_normalize_redundant_source_declaration() -> None:
    payload = json.loads(_dynamic_payload())
    payload["sections"][0]["used_source_ids"] = [2]
    payload["sections"][0]["title"] = "模型自行改写的标题"
    payload["sections"][0]["purpose"] = ""
    result = await GroundedSummaryGenerator(
        SummaryGateway(json.dumps(payload, ensure_ascii=False))
    ).summarize(
        request="从 C++ 实现角度总结，重点说明容易写错的边界",
        plan=_plan(),
        hits=(_hit(1), _hit(2)),
        section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
        model="deepseek-v4-flash",
    )

    assert result.answer.used_source_ids == (1, 2)
    assert result.quality.normalized_source_declarations == ["stack_rules"]
    assert result.quality.normalized_section_metadata == ["stack_rules"]
    assert "## 栈的操作约束" in result.answer.answer
    assert result.quality.passed is True


async def test_repeated_section_is_locally_rewritten_once() -> None:
    payload = json.loads(_dynamic_payload())
    repeated = "操作遵循固定规则，插入删除遵循固定规则，操作端点遵循固定规则。[课1]"
    payload["sections"][0]["body"] = repeated
    payload["sections"][1]["body"] = repeated.replace("[课1]", "[课2]")
    rewrite = {
        "sections": [
            {
                "key": "queue_rules",
                "title": "队列的操作约束",
                "purpose": "解释队列的操作端点并形成对比",
                "body": "队列从队尾接收新元素，并从队首移除最早进入的元素。[课2]",
                "used_source_ids": [2],
                "limitation": None,
            }
        ]
    }
    gateway = SummaryGateway(
        json.dumps(payload, ensure_ascii=False),
        json.dumps(rewrite, ensure_ascii=False),
    )
    result = await GroundedSummaryGenerator(gateway).summarize(
        request="对比总结栈和队列",
        plan=_plan(),
        hits=(_hit(1), _hit(2)),
        section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
        model="deepseek-v4-flash",
    )

    assert result.quality.rewritten_sections == ["queue_rules"]
    assert len(gateway.calls) == 2


async def test_lexical_coverage_gap_is_reported_without_brittle_rewrite() -> None:
    plan = _plan()
    sections = [section.model_copy(deep=True) for section in plan.sections]
    sections[0].required_points = ["时间复杂度"]
    plan = plan.model_copy(update={"sections": sections})
    gateway = SummaryGateway(_dynamic_payload())
    result = await GroundedSummaryGenerator(gateway).summarize(
        request="总结操作规则，必须说明时间复杂度",
        plan=plan,
        hits=(_hit(1), _hit(2)),
        section_source_ids={"stack_rules": (1,), "queue_rules": (2,)},
        model="deepseek-v4-flash",
    )

    assert result.quality.rewritten_sections == []
    assert result.quality.coverage_warnings == ["stack_rules: 时间复杂度"]
    assert len(gateway.calls) == 1
