from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph


class CourseTaskType(StrEnum):
    QUESTION = "question"
    SUMMARY = "summary"


class SummaryScopeType(StrEnum):
    COURSE = "course"
    DOCUMENTS = "documents"
    TOPIC = "topic"


@dataclass(frozen=True, slots=True)
class TaskRoutingDecision:
    task_type: CourseTaskType
    reason: str


class _RoutingState(TypedDict, total=False):
    question: str
    is_summary: bool
    decision: TaskRoutingDecision


_SUMMARY_ACTION = re.compile(
    r"(?:^|[，。！？!?\s])(?:请|麻烦|能否|可以)?\s*(?:帮我|给我)?\s*"
    r"(?:总结|概括|归纳|梳理|提炼|整理|回顾)(?:一下|下)?",
    re.IGNORECASE,
)
_SUMMARY_ARTIFACT = re.compile(
    r"(?:生成|给出|列出|制作|整理|梳理|总结).{0,12}"
    r"(?:复习提纲|知识框架|知识脉络|考试重点|重点清单|易错点)",
    re.IGNORECASE,
)
_ENGLISH_SUMMARY = re.compile(
    r"\b(?:summari[sz]e|summary|study guide|review notes|key takeaways)\b",
    re.IGNORECASE,
)
_SUMMARY_NOUN = re.compile(
    r"(?:复习提纲|知识框架|知识脉络|考试重点|重点清单|易错点汇总)",
    re.IGNORECASE,
)
_SUMMARY_AS_SUBJECT = re.compile(
    r"^(?:总结|概括|归纳).{0,12}(?:是什么|的区别|含义|如何实现|怎么实现)|"
    r"^what\s+is\s+(?:a\s+)?summary\b",
    re.IGNORECASE,
)
_CHAPTER_SCOPE = re.compile(
    r"第\s*(?:\d{1,3}|[一二三四五六七八九十百]+)\s*章|"
    r"(?:本章|这一章|当前章节|章节)",
    re.IGNORECASE,
)


class RequestRoutingGraph:
    """Route a course-chat turn without adding another model request."""

    def __init__(self) -> None:
        graph = StateGraph(_RoutingState)
        graph.add_node("classify", self._classify)
        graph.add_node("question", self._question)
        graph.add_node("summary", self._summary)
        graph.add_edge(START, "classify")
        graph.add_conditional_edges(
            "classify",
            self._route,
            {"question": "question", "summary": "summary"},
        )
        graph.add_edge("question", END)
        graph.add_edge("summary", END)
        self._graph: Any = graph.compile()

    async def route(self, question: str) -> TaskRoutingDecision:
        raw_state = await self._graph.ainvoke({"question": question})
        state = cast(_RoutingState, raw_state)
        return state["decision"]

    @staticmethod
    async def _classify(state: _RoutingState) -> _RoutingState:
        question = state["question"].strip()
        is_summary = bool(
            not _SUMMARY_AS_SUBJECT.search(question)
            and (
                _SUMMARY_ACTION.search(question)
                or _SUMMARY_ARTIFACT.search(question)
                or _ENGLISH_SUMMARY.search(question)
                or _SUMMARY_NOUN.search(question)
            )
        )
        return {"is_summary": is_summary}

    @staticmethod
    def _route(state: _RoutingState) -> str:
        return "summary" if state.get("is_summary", False) else "question"

    @staticmethod
    async def _question(state: _RoutingState) -> _RoutingState:
        _ = state["question"]
        return {
            "decision": TaskRoutingDecision(
                task_type=CourseTaskType.QUESTION,
                reason="未检测到总结指令，按课程问答处理。",
            )
        }

    @staticmethod
    async def _summary(state: _RoutingState) -> _RoutingState:
        _ = state["question"]
        return {
            "decision": TaskRoutingDecision(
                task_type=CourseTaskType.SUMMARY,
                reason="检测到总结、复习提纲或考试重点请求，已自动切换为课程总结。",
            )
        }


def summary_scope(
    question: str,
    *,
    explicit_document_scope: bool,
    selected_document_count: int,
    total_ready_document_count: int,
) -> tuple[SummaryScopeType, str]:
    """Resolve a transparent summary scope after API document filtering."""

    if explicit_document_scope or selected_document_count < total_ready_document_count:
        return (
            SummaryScopeType.DOCUMENTS,
            f"限定到 {selected_document_count} 份指定课程资料。",
        )

    normalized = question.strip().lower()
    topic_markers = (
        "知识点",
        "关于",
        "针对",
        "topic",
        "chapter",
    )
    course_markers = (
        "整门课程",
        "整个课程",
        "全课程",
        "本课程",
        "所有资料",
        "全部资料",
        "整本",
        "全书",
        "whole course",
        "all materials",
    )
    if _CHAPTER_SCOPE.search(normalized) or any(
        marker in normalized for marker in topic_markers
    ):
        return SummaryScopeType.TOPIC, "按请求中指定的章节或知识点进行总结。"
    if any(marker in normalized for marker in course_markers):
        return SummaryScopeType.COURSE, "覆盖当前课程的全部已索引资料。"
    return SummaryScopeType.COURSE, "未指定更小范围，默认总结当前课程。"


def summary_retrieval_query(question: str, scope: SummaryScopeType) -> str:
    normalized = " ".join(question.split())
    facets = "核心概念 重点知识 知识关系 常见错误 示例应用 复习建议 考试重点"
    return f"{normalized}；请覆盖：{facets}"
