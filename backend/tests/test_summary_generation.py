from __future__ import annotations

import pytest

from app.core.exceptions import LLMOutputError
from app.generation import ChatCompletion, GroundedSummaryGenerator, TokenUsage
from app.knowledge import VectorSearchResult
from app.orchestration import SummaryScopeType


class SummaryGateway:
    def __init__(self, content: str) -> None:
        self.content = content

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        assert "exam_focus" in system_prompt
        assert "总结范围类型：course" in user_prompt
        assert "后进先出" in user_prompt
        return ChatCompletion(
            content=self.content,
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


def _hit() -> VectorSearchResult:
    return VectorSearchResult(
        point_id="summary-1",
        score=0.02,
        course_id="course-1",
        document_id="document-1",
        chunk_index=0,
        text="栈遵循后进先出原则，插入和删除都在栈顶进行。",
        payload={"file_name": "讲义.md", "section_path": ["栈", "基本概念"]},
    )


def _payload(citation: str = "[课1]") -> str:
    return (
        '{"sufficient_evidence":true,'
        f'"core_concepts":"栈遵循后进先出。{citation}",'
        f'"key_knowledge":"操作集中在栈顶。{citation}",'
        f'"knowledge_relationships":"栈顶统一承载插入和删除。{citation}",'
        f'"common_mistakes":"不要把栈误认为先进先出。{citation}",'
        f'"examples_and_applications":"可依据栈顶操作理解其行为。{citation}",'
        '"review_recommendations":"先复习定义，再比较操作位置。",'
        f'"exam_focus":"重点掌握后进先出与栈顶。{citation}",'
        '"used_source_ids":[1]}'
    )


async def test_summary_generator_builds_fixed_sections_and_verified_references() -> None:
    generator = GroundedSummaryGenerator(
        SummaryGateway(_payload()),
    )

    answer, eligible = await generator.summarize(
        request="总结整个课程",
        scope=SummaryScopeType.COURSE,
        scope_description="覆盖全部资料",
        hits=(_hit(),),
        model="deepseek-v4-flash",
    )

    assert answer.used_source_ids == (1,)
    assert len(eligible) == 1
    for heading in (
        "## 核心概念",
        "## 重点知识",
        "## 知识关系",
        "## 常见错误",
        "## 示例或应用",
        "## 复习建议",
        "## 考试重点",
        "## 资料引用",
    ):
        assert heading in answer.answer
    assert "- [课1] 讲义.md · 栈 › 基本概念" in answer.answer


async def test_summary_generator_rejects_external_or_unnamespaced_citations() -> None:
    for citation in ("[外1]", "[1]"):
        generator = GroundedSummaryGenerator(
            SummaryGateway(_payload(citation)),
        )
        with pytest.raises(LLMOutputError):
            await generator.summarize(
                request="总结整个课程",
                scope=SummaryScopeType.COURSE,
                scope_description="覆盖全部资料",
                hits=(_hit(),),
                model="deepseek-v4-flash",
            )
