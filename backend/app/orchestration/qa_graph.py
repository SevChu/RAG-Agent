from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from app.external_search import (
    ExternalSearchEvidence,
    ExternalSearchGateway,
    ExternalSearchResult,
    ExternalSearchStatus,
)
from app.generation import (
    AnswerScope,
    AnswerStyle,
    ChatCompletionGateway,
    GroundedAnswer,
    GroundedAnswerGenerator,
    MixedGroundedAnswerGenerator,
)
from app.knowledge.models import VectorSearchResult

_EXPLICIT_EXTERNAL_MARKERS = (
    "外部",
    "联网",
    "网上",
    "搜索",
    "查找资料",
    "补充资料",
    "官方文档",
    "论文",
    "最新研究",
    "web search",
)
_TIME_SENSITIVE_MARKERS = (
    "最新",
    "截至",
    "今年",
    "今天",
    "近期",
    "新版本",
    "latest",
    "current",
    "recent",
    "today",
)
_CONTEXTUAL_TIME_MARKERS = ("当前", "目前", "现在", "current")
_TIME_CONTEXT_MARKERS = (
    "版本",
    "发布",
    "更新",
    "标准",
    "规范",
    "官方",
    "支持情况",
    "研究进展",
    "version",
    "release",
    "update",
)
_MULTI_PART_MARKERS = ("以及", "并且", "同时", "分别说明", "比较", "区别", "优缺点")


@dataclass(frozen=True, slots=True)
class SearchDecision:
    should_search: bool
    reason: str


@dataclass(frozen=True, slots=True)
class GraphAnswerResult:
    answer: GroundedAnswer
    eligible_course_hits: tuple[VectorSearchResult, ...]
    external_result: ExternalSearchResult | None
    external_evidence: tuple[ExternalSearchEvidence, ...]
    decision: SearchDecision
    fallback_applied: bool


class _AnswerGraphState(TypedDict, total=False):
    question: str
    standalone_question: str
    style: AnswerStyle
    scope: AnswerScope
    model: str
    course_hits: tuple[VectorSearchResult, ...]
    eligible_course_hits: tuple[VectorSearchResult, ...]
    decision: SearchDecision
    external_result: ExternalSearchResult | None
    external_evidence: tuple[ExternalSearchEvidence, ...]
    answer: GroundedAnswer
    fallback_applied: bool


class ConditionalAnswerGraph:
    """LangGraph orchestration for coverage-based Web Search and answer generation."""

    def __init__(
        self,
        *,
        llm: ChatCompletionGateway,
        external_search: ExternalSearchGateway,
        min_similarity_score: float,
        external_trigger_score: float,
        external_search_enabled: bool,
        provider: str,
    ) -> None:
        self.llm = llm
        self.external_search = external_search
        self.min_similarity_score = min_similarity_score
        self.external_trigger_score = external_trigger_score
        self.external_search_enabled = external_search_enabled
        self.provider = provider

        builder = StateGraph(_AnswerGraphState)
        builder.add_node("assess_coverage", self._assess_coverage)
        builder.add_node("search_external", self._search_external)
        builder.add_node("generate_answer", self._generate_answer)
        builder.add_edge(START, "assess_coverage")
        builder.add_conditional_edges(
            "assess_coverage",
            self._route_after_assessment,
            {
                "search_external": "search_external",
                "generate_answer": "generate_answer",
            },
        )
        builder.add_edge("search_external", "generate_answer")
        builder.add_edge("generate_answer", END)
        self._graph: Any = builder.compile()

    async def run(
        self,
        *,
        question: str,
        standalone_question: str,
        style: AnswerStyle,
        scope: AnswerScope,
        model: str,
        course_hits: tuple[VectorSearchResult, ...],
    ) -> GraphAnswerResult:
        initial: _AnswerGraphState = {
            "question": question,
            "standalone_question": standalone_question,
            "style": style,
            "scope": scope,
            "model": model,
            "course_hits": course_hits,
            "external_result": None,
            "external_evidence": (),
            "fallback_applied": False,
        }
        raw_result = await self._graph.ainvoke(initial)
        state = cast(_AnswerGraphState, raw_result)
        return GraphAnswerResult(
            answer=state["answer"],
            eligible_course_hits=state["eligible_course_hits"],
            external_result=state.get("external_result"),
            external_evidence=state.get("external_evidence", ()),
            decision=state["decision"],
            fallback_applied=state.get("fallback_applied", False),
        )

    async def _assess_coverage(self, state: _AnswerGraphState) -> _AnswerGraphState:
        eligible_hits = tuple(
            hit
            for hit in state["course_hits"]
            if hit.score >= self.min_similarity_score
        )
        decision = self._decide_search(
            question=state["question"],
            standalone_question=state["standalone_question"],
            scope=state["scope"],
            eligible_hits=eligible_hits,
        )
        return {"eligible_course_hits": eligible_hits, "decision": decision}

    def _route_after_assessment(
        self,
        state: _AnswerGraphState,
    ) -> Literal["search_external", "generate_answer"]:
        return "search_external" if state["decision"].should_search else "generate_answer"

    async def _search_external(self, state: _AnswerGraphState) -> _AnswerGraphState:
        started_at = perf_counter()
        try:
            result = await self.external_search.search(
                query=state["standalone_question"],
                model=state["model"],
            )
        except Exception:  # pragma: no cover - protects course fallback from adapter bugs
            result = ExternalSearchResult(
                query=state["standalone_question"],
                status=ExternalSearchStatus.FAILED,
                results=(),
                raw_result_count=0,
                provider=self.provider,
                model=state["model"],
                elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
                failure_reason="外部检索发生未预期错误，已保护性降级。",
            )
        usable_evidence = (
            result.results
            if result.status is ExternalSearchStatus.SUCCEEDED
            else ()
        )
        fallback_applied = (
            not usable_evidence
            and bool(state["eligible_course_hits"])
        )
        return {
            "external_result": result,
            "external_evidence": usable_evidence,
            "fallback_applied": fallback_applied,
        }

    async def _generate_answer(self, state: _AnswerGraphState) -> _AnswerGraphState:
        external_evidence = state.get("external_evidence", ())
        if external_evidence:
            answer, _ = await MixedGroundedAnswerGenerator(
                self.llm,
                min_similarity_score=self.min_similarity_score,
            ).answer(
                question=state["question"],
                standalone_question=state["standalone_question"],
                course_hits=state["course_hits"],
                external_evidence=external_evidence,
                style=state["style"],
                model=state["model"],
            )
        else:
            answer, _ = await GroundedAnswerGenerator(
                self.llm,
                min_similarity_score=self.min_similarity_score,
            ).answer(
                question=state["question"],
                standalone_question=state["standalone_question"],
                hits=state["course_hits"],
                style=state["style"],
                model=state["model"],
            )
        return {"answer": answer}

    def _decide_search(
        self,
        *,
        question: str,
        standalone_question: str,
        scope: AnswerScope,
        eligible_hits: tuple[VectorSearchResult, ...],
    ) -> SearchDecision:
        if scope is AnswerScope.COURSE_ONLY:
            return SearchDecision(False, "仅课程资料模式已关闭外部检索。")
        if not self.external_search_enabled:
            return SearchDecision(False, "外部检索已由服务端配置关闭。")

        normalized = f"{question} {standalone_question}".lower()
        if any(marker in normalized for marker in _EXPLICIT_EXTERNAL_MARKERS):
            return SearchDecision(True, "用户问题明确要求外部资料或联网核验。")
        if _is_time_sensitive(normalized):
            return SearchDecision(True, "问题具有明显时效性，需要外部资料。")
        if not eligible_hits:
            return SearchDecision(True, "课程检索没有取得达到证据阈值的内容。")

        highest_score = max(hit.score for hit in eligible_hits)
        if highest_score < self.external_trigger_score:
            return SearchDecision(True, "课程证据相关度不足，需要外部资料补足。")
        if len(eligible_hits) < 2 and any(
            marker in normalized for marker in _MULTI_PART_MARKERS
        ):
            return SearchDecision(True, "课程证据不足以覆盖问题中的多个子要求。")
        return SearchDecision(False, "课程证据已覆盖问题，未触发外部检索。")


def _is_time_sensitive(query: str) -> bool:
    if any(marker in query for marker in _TIME_SENSITIVE_MARKERS):
        return True
    return any(marker in query for marker in _CONTEXTUAL_TIME_MARKERS) and any(
        marker in query for marker in _TIME_CONTEXT_MARKERS
    )
