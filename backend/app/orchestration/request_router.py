from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph


class CourseTaskType(StrEnum):
    QUESTION = "question"
    SUMMARY = "summary"
    EXAM = "exam"


class SummaryScopeType(StrEnum):
    COURSE = "course"
    DOCUMENTS = "documents"
    TOPIC = "topic"


@dataclass(frozen=True, slots=True)
class TaskRoutingDecision:
    task_type: CourseTaskType
    reason: str


@dataclass(frozen=True, slots=True)
class ExamFollowUpOutput:
    include_answers: bool
    include_explanations: bool


class _RoutingState(TypedDict, total=False):
    question: str
    is_summary: bool
    is_exam: bool
    decision: TaskRoutingDecision


_SUMMARY_ACTION = re.compile(
    r"(?:^|[，。！？!?\s])(?:请|麻烦|能否|可以)?\s*(?:帮我|给我)?\s*"
    r"(?:总结|概括|归纳|梳理|提炼|整理|回顾)(?:一下|下)?",
    re.IGNORECASE,
)
_SUMMARY_VERB = re.compile(
    r"(?:总结|概括|归纳|梳理|提炼|整理|回顾)",
    re.IGNORECASE,
)
_EMBEDDED_SUMMARY_ACTION = re.compile(
    r"(?:^|[，。！？!?\s])(?:请|麻烦|能否|可以)?\s*(?:帮我|给我)?\s*"
    r"(?:从|按|以|围绕|针对).{1,50}(?:总结|概括|归纳|梳理|提炼|整理|回顾)",
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
    r"^(?:请(?:解释|说明|问)?|解释|说明|什么是)?\s*(?:总结|概括|归纳).{0,12}"
    r"(?:是什么|的区别|含义|如何实现|怎么实现)|"
    r"^(?:什么是|如何理解|怎么理解).{0,12}(?:总结|概括|归纳)|"
    r"^what\s+is\s+(?:a\s+)?summary\b",
    re.IGNORECASE,
)
_CHAPTER_SCOPE = re.compile(
    r"第\s*(?:\d{1,3}|[一二三四五六七八九十百]+)\s*章|"
    r"(?:本章|这一章|当前章节|章节)",
    re.IGNORECASE,
)
_EXAM_PAPER = (
    r"(?:试卷|卷子|"
    r"(?:模拟|单元|章节|期中|期末|综合|练习|测试|随堂|复习)卷)"
)
_EXAM_ACTION = re.compile(
    r"(?:出题|组卷|命题)|"
    r"(?:生成|制作|整理|设计|编制|拟定|出).{0,24}"
    rf"(?:试题|题目|练习题|测试题|模拟题|{_EXAM_PAPER})|"
    rf"(?:给我|给出|来)\s*(?:一|1)?\s*(?:份|套|张)?\s*{_EXAM_PAPER}|"
    r"(?:给我|给出|来|出)\s*(?:\d+\s*(?:道|个)?\s*)"
    r"(?:单选题|多选题|选择题|判断题|简答题|编程题|练习题|试题|题目|题)",
    re.IGNORECASE,
)
_EXAM_ARTIFACT = re.compile(
    rf"(?:{_EXAM_PAPER}).{{0,16}}\d+\s*(?:道|个)?题|"
    r"(?:题目清单|题库练习)|"
    r"\b(?:create|generate|make)\s+(?:an?\s+)?(?:quiz|exam|test|question set)\b",
    re.IGNORECASE,
)
_EXAM_AS_SUBJECT = re.compile(
    rf"^.{{0,16}}(?:如何|怎么|为什么|为何).{{0,30}}"
    rf"(?:出题|组卷|命题|生成|制作|设计|编制).{{0,20}}(?:试题|题目|{_EXAM_PAPER})|"
    rf"^(?:什么是|如何理解|怎么理解).{{0,20}}(?:出题|组卷|命题|{_EXAM_PAPER})|"
    rf"(?:出题|组卷|命题|{_EXAM_PAPER}).{{0,16}}(?:是什么|的区别|含义|原则|流程|方法)[？?]?$",
    re.IGNORECASE,
)
_EXAM_FOLLOW_UP_OUTPUT = re.compile(
    r"(?:给出|提供|补充|显示|输出|公布|查看|告诉我).{0,20}"
    r"(?:参考)?(?:答案|解析|讲解)|"
    r"(?:答案|解析|讲解).{0,12}(?:给出|提供|补充|显示|输出|公布)",
    re.IGNORECASE,
)
_ANSWER_TERM = re.compile(r"(?:参考)?答案", re.IGNORECASE)
_EXPLANATION_TERM = re.compile(r"解析|讲解", re.IGNORECASE)
_OMIT_EXPLANATION = re.compile(
    r"(?:不要|不用|无需|不需要|不含|没有|无).{0,8}(?:解析|讲解)|"
    r"(?:解析|讲解).{0,8}(?:不要|不用|无需|不需要)",
    re.IGNORECASE,
)


def exam_follow_up_output(question: str) -> ExamFollowUpOutput | None:
    """Resolve an output-only continuation for the immediately preceding exam.

    The caller must additionally prove that the latest completed assistant turn is
    an exam. Keeping that contextual gate outside this text-only helper prevents a
    standalone question about "answers and explanations" from being misrouted.
    """

    normalized = " ".join(question.split())
    if not _EXAM_FOLLOW_UP_OUTPUT.search(normalized):
        return None
    asks_for_answer = bool(_ANSWER_TERM.search(normalized))
    asks_for_explanation = bool(_EXPLANATION_TERM.search(normalized)) and not bool(
        _OMIT_EXPLANATION.search(normalized)
    )
    if not asks_for_answer and not asks_for_explanation:
        return None
    return ExamFollowUpOutput(
        include_answers=True,
        include_explanations=asks_for_explanation,
    )


class RequestRoutingGraph:
    """Route a course-chat turn without adding another model request."""

    def __init__(self) -> None:
        graph = StateGraph(_RoutingState)
        graph.add_node("classify", self._classify)
        graph.add_node("question", self._question)
        graph.add_node("summary", self._summary)
        graph.add_node("exam", self._exam)
        graph.add_edge(START, "classify")
        graph.add_conditional_edges(
            "classify",
            self._route,
            {"question": "question", "summary": "summary", "exam": "exam"},
        )
        graph.add_edge("question", END)
        graph.add_edge("summary", END)
        graph.add_edge("exam", END)
        self._graph: Any = graph.compile()

    async def route(self, question: str) -> TaskRoutingDecision:
        raw_state = await self._graph.ainvoke({"question": question})
        state = cast(_RoutingState, raw_state)
        return state["decision"]

    @staticmethod
    async def _classify(state: _RoutingState) -> _RoutingState:
        question = state["question"].strip()
        is_exam = bool(
            not _EXAM_AS_SUBJECT.search(question)
            and (_EXAM_ACTION.search(question) or _EXAM_ARTIFACT.search(question))
        )
        is_summary = bool(
            not is_exam
            and not _SUMMARY_AS_SUBJECT.search(question)
            and (
                _SUMMARY_ACTION.search(question)
                or _SUMMARY_VERB.search(question)
                or _EMBEDDED_SUMMARY_ACTION.search(question)
                or _SUMMARY_ARTIFACT.search(question)
                or _ENGLISH_SUMMARY.search(question)
                or _SUMMARY_NOUN.search(question)
            )
        )
        return {"is_summary": is_summary, "is_exam": is_exam}

    @staticmethod
    def _route(state: _RoutingState) -> str:
        if state.get("is_exam", False):
            return "exam"
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

    @staticmethod
    async def _exam(state: _RoutingState) -> _RoutingState:
        _ = state["question"]
        return {
            "decision": TaskRoutingDecision(
                task_type=CourseTaskType.EXAM,
                reason="检测到出题或组卷请求，已自动切换为混合试卷生成。",
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
