from app.orchestration import (
    CourseTaskType,
    RequestRoutingGraph,
    SummaryScopeType,
    exam_follow_up_output,
    summary_scope,
)


async def test_router_detects_common_summary_requests() -> None:
    router = RequestRoutingGraph()

    for request in (
        "请帮我总结整个课程",
        "梳理一下第三章的知识框架",
        "请从操作端点角度对比总结栈和队列，不要考试建议",
        "只总结第三章最值得考前复习的内容",
        "对比总结栈和队列最容易混淆的条件",
        "把快速排序总结成递归流程",
        "只用反例和错误做法总结指针",
        "同时总结图遍历的流程和复杂度",
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
        "请解释总结和回答的区别是什么？",
        "什么是课程总结？",
    ):
        decision = await router.route(request)
        assert decision.task_type is CourseTaskType.QUESTION


async def test_router_detects_exam_requests_before_summary_requests() -> None:
    router = RequestRoutingGraph()

    for request in (
        "请按第三章出20题",
        "生成一份包含答案和解析的模拟试卷",
        "请根据第三章的内容出一份单元试卷，但不要答案和解析。",
        "请给出一份有关于栈相关知识点的试卷，不用提供答案和解析",
        "请根据第三章的内容出一份模拟卷，但只要答案，暂时不用输出解析。",
        "围绕第五章设计一套难度适中的章节卷子",
        "给我5道判断题和2道C++编程题",
        "根据刚才的总结组卷，重点考边界条件",
        "Create a quiz for chapter 3",
    ):
        decision = await router.route(request)
        assert decision.task_type is CourseTaskType.EXAM

    summary = await router.route("总结第三章的考试重点")
    assert summary.task_type is CourseTaskType.SUMMARY


async def test_router_keeps_questions_about_exam_artifacts_as_qa() -> None:
    router = RequestRoutingGraph()

    for request in (
        "单元试卷和期末试卷有什么区别？",
        "试卷通常包含哪些结构？",
        "教师应该如何设计一份模拟卷？",
        "组卷的基本原则是什么？",
    ):
        decision = await router.route(request)
        assert decision.task_type is CourseTaskType.QUESTION


def test_exam_follow_up_output_requires_an_output_action() -> None:
    both = exam_follow_up_output("现在给出答案和解析。")
    answers_only = exam_follow_up_output("接着公布参考答案，不要解析")

    assert both is not None
    assert both.include_answers is True
    assert both.include_explanations is True
    assert answers_only is not None
    assert answers_only.include_answers is True
    assert answers_only.include_explanations is False
    assert exam_follow_up_output("答案和解析有什么区别？") is None
    assert exam_follow_up_output("这道题为什么这样解？") is None


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
