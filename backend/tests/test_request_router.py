from app.orchestration import (
    CourseTaskType,
    RequestRoutingGraph,
    SummaryScopeType,
    summary_scope,
)


async def test_router_detects_common_summary_requests() -> None:
    router = RequestRoutingGraph()

    for request in (
        "请帮我总结整个课程",
        "梳理一下第三章的知识框架",
        "这章考试重点有哪些？",
        "Create a study guide for this course",
    ):
        decision = await router.route(request)
        assert decision.task_type is CourseTaskType.SUMMARY


async def test_router_keeps_normal_questions_and_summary_term_questions_as_qa() -> None:
    router = RequestRoutingGraph()

    for request in (
        "什么是栈？",
        "总结和回答的区别是什么？",
        "What is a summary?",
    ):
        decision = await router.route(request)
        assert decision.task_type is CourseTaskType.QUESTION


def test_summary_scope_prefers_explicit_documents_then_topic_then_course() -> None:
    explicit, _ = summary_scope(
        "总结讲义.md",
        explicit_document_scope=True,
        selected_document_count=1,
        total_ready_document_count=1,
    )
    topic, _ = summary_scope(
        "总结第三章的考试重点",
        explicit_document_scope=False,
        selected_document_count=2,
        total_ready_document_count=2,
    )
    course, _ = summary_scope(
        "总结整个课程",
        explicit_document_scope=False,
        selected_document_count=2,
        total_ready_document_count=2,
    )

    assert explicit is SummaryScopeType.DOCUMENTS
    assert topic is SummaryScopeType.TOPIC
    assert course is SummaryScopeType.COURSE
