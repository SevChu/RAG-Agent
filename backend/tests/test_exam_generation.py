from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

from app.core.exceptions import LLMOutputError
from app.external_search import ExternalSearchEvidence, ExternalSourceQuality
from app.generation import (
    AnswerStatus,
    ChatCompletion,
    GroundedExamGenerator,
    TokenUsage,
    build_exam_plan,
)
from app.knowledge import VectorSearchResult


class ExamGateway:
    def __init__(self, *contents: str, review_contents: list[str] | None = None) -> None:
        self.contents = list(contents)
        self.review_contents = list(review_contents or [])
        self.review_prompts: list[str] = []
        self.calls = 0

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        self.calls += 1
        assert "json" in system_prompt.lower()
        if "审查器" in system_prompt:
            self.review_prompts.append(user_prompt)
            if self.review_contents:
                content = self.review_contents.pop(0)
            else:
                numbers = list(
                    dict.fromkeys(
                        int(value)
                        for value in re.findall(r'"number":\s*(\d+)', user_prompt)
                    )
                )
                content = json.dumps(
                    {
                        "results": [
                            {
                                "number": number,
                                "supported": True,
                                "unsupported_claim": None,
                            }
                            for number in numbers
                        ]
                    },
                    ensure_ascii=False,
                )
            return ChatCompletion(content=content, model=model)
        assert self.contents
        return ChatCompletion(
            content=self.contents.pop(0),
            model=model,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=80, total_tokens=180),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("exam generation must use JSON completion")


class DefaultExamDriftGateway:
    def __init__(self) -> None:
        self.calls = 0
        self.short_choice_emitted = False
        self.review_prompts: list[str] = []

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        self.calls += 1
        if "审查器" in system_prompt:
            self.review_prompts.append(user_prompt)
            numbers = list(
                dict.fromkeys(
                    int(value)
                    for value in re.findall(r'"number":\s*(\d+)', user_prompt)
                )
            )
            return ChatCompletion(
                content=json.dumps(
                    {
                        "results": [
                            {"number": number, "supported": True}
                            for number in numbers
                        ]
                    },
                    ensure_ascii=False,
                ),
                model=model,
            )

        slots = re.findall(
            r"number=(\d+), type=([a-z_]+), difficulty=([a-z_]+)",
            user_prompt,
        )
        assert slots
        questions: list[dict[str, object]] = []
        topic_names = (
            "后进先出定义",
            "栈顶插入规则",
            "栈顶删除规则",
            "空栈状态判断",
            "顺序栈容量边界",
            "栈满状态判断",
            "入栈操作步骤",
            "出栈操作步骤",
            "栈顶元素读取",
            "括号匹配应用",
            "表达式求值应用",
            "递归调用关系",
            "顺序栈存储特点",
            "链栈存储特点",
            "上溢边界处理",
            "下溢边界处理",
            "栈操作综合比较",
            "顺序栈入栈实现",
            "顺序栈出栈实现",
            "栈顶读取实现",
        )
        for raw_number, question_type, difficulty in slots:
            number = int(raw_number)
            options: list[str] = []
            answer: str | None = "正确"
            input_description: str | None = None
            output_description: str | None = None
            constraints: list[str] = []
            samples: list[str] = []
            reference_code: str | None = None
            if question_type in {"single_choice", "multiple_choice"}:
                options = ["选项甲", "选项乙", "选项丙", "选项丁"]
                if number == 5 and not self.short_choice_emitted:
                    options = options[:3]
                    self.short_choice_emitted = True
                answer = "A" if question_type == "single_choice" else "A、B"
            elif question_type == "short_answer":
                answer = f"第 {number} 题的简要答案。"
            elif question_type == "programming":
                answer = None
                input_description = "输入一个整数。"
                output_description = "输出操作后的栈顶整数。"
                constraints = ["栈容量至少为 1"]
                samples = ["输入：3；输出：3"]
                reference_code = "int main() { return 0; }"
            questions.append(
                {
                    "number": number,
                    "question_type": question_type,
                    "difficulty": difficulty,
                    "knowledge_point": topic_names[number - 1],
                    "prompt": f"围绕{topic_names[number - 1]}完成第 {number} 题。",
                    "options": options,
                    "answer": answer,
                    "explanation": None,
                    "source_mode": "course_generated",
                    "course_source_ids": [1],
                    "external_source_ids": [],
                    "input_description": input_description,
                    "output_description": output_description,
                    "constraints": constraints,
                    "samples": samples,
                    "reference_code": reference_code,
                    "complexity_analysis": None,
                    "test_case_design": [],
                }
            )
        return ChatCompletion(
            content=json.dumps({"questions": questions}, ensure_ascii=False),
            model=model,
            usage=TokenUsage(prompt_tokens=100, completion_tokens=80, total_tokens=180),
        )

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("exam generation must use JSON completion")


def _course_hit(index: int, *, exercise: bool = False) -> VectorSearchResult:
    text = (
        "判断：栈中元素的插入和删除只能在栈顶进行。"
        if exercise
        else "栈遵循后进先出原则，插入和删除都在栈顶进行。"
    )
    return VectorSearchResult(
        point_id=f"exam-{index}",
        score=0.92 - index / 100,
        course_id="course-1",
        document_id="document-1",
        chunk_index=index,
        text=text,
        payload={
            "file_name": "讲义.md",
            "content_role": "exercise_question" if exercise else "exposition",
        },
    )


def _external() -> ExternalSearchEvidence:
    return ExternalSearchEvidence(
        rank=1,
        title="University stack exercises",
        publisher="Example University",
        url="https://example.edu/stacks",
        accessed_at=datetime(2026, 8, 6, tzinfo=UTC),
        evidence_excerpt="A stack exercise asks learners to trace push and pop operations.",
        quality=ExternalSourceQuality.INSTITUTIONAL,
    )


def _question(
    number: int,
    *,
    prompt: str | None = None,
    external: bool = False,
) -> dict[str, object]:
    return {
        "number": number,
        "question_type": "true_false",
        "difficulty": "easy",
        "knowledge_point": f"栈的性质 {number}",
        "prompt": prompt or f"判断题 {number}：执行第 {number} 次入栈后栈顶发生变化。",
        "options": [],
        "answer": "正确",
        "explanation": "入栈操作会把新元素放到栈顶。",
        "source_mode": "external_supplement" if external else "course_generated",
        "course_source_ids": [] if external else [1],
        "external_source_ids": [1] if external else [],
        "input_description": None,
        "output_description": None,
        "constraints": [],
        "samples": [],
        "reference_code": None,
        "complexity_analysis": None,
        "test_case_design": [],
    }


def _payload(*questions: dict[str, object]) -> str:
    return json.dumps({"questions": list(questions)}, ensure_ascii=False)


def test_default_exam_plan_applies_confirmed_limits_and_distribution() -> None:
    plan = build_exam_plan("请根据第三章组卷", allow_external=True)

    assert plan.question_count == 20
    assert plan.programming_language == "C++"
    assert {item.key: item.count for item in plan.type_distribution} == {
        "single_choice": 6,
        "multiple_choice": 2,
        "true_false": 4,
        "short_answer": 5,
        "programming": 3,
    }
    assert {item.key: item.count for item in plan.difficulty_distribution} == {
        "easy": 6,
        "medium": 10,
        "hard": 4,
    }
    assert plan.max_course_adapted_count == 6
    assert plan.max_external_count == 4


def test_exam_plan_respects_explicit_counts_language_and_output_options() -> None:
    plan = build_exam_plan(
        "共10题：4道单选题、2道判断题、4道Python编程题，只要题目不要答案",
        allow_external=False,
    )

    assert plan.question_count == 10
    assert plan.programming_language == "Python"
    assert plan.include_answers is False
    assert plan.include_explanations is False
    assert plan.max_external_count == 0
    assert {item.key: item.count for item in plan.type_distribution if item.count} == {
        "single_choice": 4,
        "true_false": 2,
        "programming": 4,
    }


def test_exam_plan_understands_deferred_answers_and_explanations() -> None:
    plan = build_exam_plan(
        "根据当前课程生成一份试卷，先不用给答案和解析。",
        allow_external=True,
    )

    assert plan.question_count == 20
    assert plan.include_answers is False
    assert plan.include_explanations is False


@pytest.mark.parametrize(
    "output_instruction",
    [
        "暂时不需要提供参考答案",
        "答案先不用给",
        "无需附上答案",
        "仅题目即可",
    ],
)
def test_exam_plan_understands_common_no_answer_phrasings(
    output_instruction: str,
) -> None:
    plan = build_exam_plan(
        f"出1道判断题，{output_instruction}",
        allow_external=False,
    )

    assert plan.include_answers is False
    assert plan.include_explanations is False


def test_exam_plan_can_keep_answers_while_omitting_explanations() -> None:
    plan = build_exam_plan(
        "出1道判断题，需要答案，但先不用提供解析",
        allow_external=False,
    )

    assert plan.include_answers is True
    assert plan.include_explanations is False


@pytest.mark.asyncio
async def test_default_twenty_question_exam_recovers_choice_and_programming_drift() -> None:
    request_text = (
        "请根据第三章的内容出一份模拟卷，但只要答案，暂时不用输出解析。"
    )
    plan = build_exam_plan(request_text, allow_external=True)
    gateway = DefaultExamDriftGateway()

    result = await GroundedExamGenerator(gateway).generate(
        request=request_text,
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.quality.generated_question_count == 20
    assert result.quality.answers_included is True
    assert result.quality.explanations_included is False
    assert gateway.short_choice_emitted is True
    assert "## 5. 单项选择题" in result.answer.answer
    assert "- D. 选项丁" in result.answer.answer
    assert "## 18. 编程题" in result.answer.answer
    assert result.answer.answer.count("**答案：** 见参考代码。") == 3
    assert "**解析：**" not in result.answer.answer
    assert "**复杂度：**" not in result.answer.answer


@pytest.mark.asyncio
async def test_sorting_question_only_exam_keeps_internal_key_but_hides_it() -> None:
    request_text = "请根据书中排序章节出一份模拟卷，但答案和解析都不要。"
    plan = build_exam_plan(request_text, allow_external=False)
    gateway = DefaultExamDriftGateway()

    result = await GroundedExamGenerator(gateway).generate(
        request=request_text,
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.quality.generated_question_count == 20
    assert result.quality.answers_included is False
    assert result.quality.explanations_included is False
    assert result.answer.answer.count("\n## ") == 20
    assert "**答案：**" not in result.answer.answer
    assert "**解析：**" not in result.answer.answer
    assert "int main()" not in result.answer.answer
    assert gateway.review_prompts
    assert '"answer": "正确"' in gateway.review_prompts[0]
    assert "见参考代码。" in gateway.review_prompts[0]


@pytest.mark.asyncio
async def test_question_only_exam_locally_retries_missing_internal_answer() -> None:
    plan = build_exam_plan(
        "根据当前课程出1道判断题，先不用给答案和解析。",
        allow_external=False,
    )
    incomplete = _question(1)
    incomplete["answer"] = None
    repaired = _question(1)
    gateway = ExamGateway(_payload(incomplete), _payload(repaired))

    result = await GroundedExamGenerator(gateway).generate(
        request="根据当前课程出1道判断题，先不用给答案和解析。",
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert "**答案：**" not in result.answer.answer
    assert "**解析：**" not in result.answer.answer
    assert result.quality.answers_included is False
    assert result.quality.explanations_included is False
    assert gateway.calls == 3
    assert gateway.review_prompts
    assert '"answer": "正确"' in gateway.review_prompts[0]


@pytest.mark.asyncio
async def test_exam_generator_locally_retries_incomplete_no_answer_programming_batch() -> None:
    request_text = "请出1道C++编程题，不用提供答案和解析，仅课程资料"
    plan = build_exam_plan(request_text, allow_external=False)
    incomplete = _question(1)
    incomplete.update(
        {
            "question_type": "programming",
            "prompt": "编写程序，使用栈完成一次入栈操作。",
            "answer": None,
            "explanation": None,
            "input_description": "输入一个待入栈的整数。",
            "output_description": "输出入栈后的栈顶元素。",
            "constraints": ["栈的容量至少为 1"],
            "samples": [],
            "reference_code": None,
            "complexity_analysis": None,
            "test_case_design": [],
        }
    )
    repaired = {
        **incomplete,
        "answer": "读取一个整数，将其压入栈后输出该元素。",
        "samples": ["输入：3；输出：3"],
        "reference_code": "int main() { int value; cin >> value; cout << value; }",
    }
    gateway = ExamGateway(_payload(incomplete), _payload(repaired))

    result = await GroundedExamGenerator(gateway).generate(
        request=request_text,
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert "**输入：** 输入一个待入栈的整数。" in result.answer.answer
    assert "输入：3；输出：3" in result.answer.answer
    assert "**答案：**" not in result.answer.answer
    assert "参考代码" not in result.answer.answer
    assert "测试用例设计" not in result.answer.answer
    assert gateway.calls == 3


@pytest.mark.asyncio
async def test_exam_generator_normalizes_programming_answer_to_reference_code() -> None:
    request_text = (
        "请根据第三章的内容出一份仅含1道C++编程题的模拟卷，"
        "但只要答案，暂时不用输出解析。"
    )
    plan = build_exam_plan(request_text, allow_external=False)
    question = _question(1)
    question.update(
        {
            "question_type": "programming",
            "prompt": "编写程序，使用栈完成一次入栈操作。",
            "answer": None,
            "explanation": None,
            "input_description": "输入一个待入栈的整数。",
            "output_description": "输出入栈后的栈顶元素。",
            "constraints": ["栈的容量至少为 1"],
            "samples": ["输入：3；输出：3"],
            "reference_code": "int main() { return 0; }",
            "complexity_analysis": "时间复杂度 O(1)。",
            "test_case_design": ["测试一个普通整数入栈。"],
        }
    )
    gateway = ExamGateway(_payload(question))

    result = await GroundedExamGenerator(gateway).generate(
        request=request_text,
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert "**答案：** 见参考代码。" in result.answer.answer
    assert "int main() { return 0; }" in result.answer.answer
    assert "**解析：**" not in result.answer.answer
    assert "**复杂度：**" not in result.answer.answer
    assert "**测试用例设计：**" not in result.answer.answer
    assert result.quality.answers_included is True
    assert result.quality.explanations_included is False
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_exam_generator_normalizes_choice_objects_and_fenced_json() -> None:
    request_text = "出1道单选题，只要答案，不要解析，仅课程资料"
    plan = build_exam_plan(request_text, allow_external=False)
    question = _question(1)
    question.update(
        {
            "question_type": "single_choice",
            "prompt": "栈遵循哪一种访问次序？",
            "options": {
                "A": "后进先出",
                "B": "先进先出",
                "C": "随机访问",
                "D": "按优先级访问",
            },
            "answer": "A",
            "explanation": None,
        }
    )
    fenced = f"```json\n{_payload(question)}\n```"
    gateway = ExamGateway(fenced)

    result = await GroundedExamGenerator(gateway).generate(
        request=request_text,
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert "- A. 后进先出" in result.answer.answer
    assert "- D. 按优先级访问" in result.answer.answer
    assert "**答案：** A" in result.answer.answer
    assert "**解析：**" not in result.answer.answer
    assert '"options": ["A. 后进先出"' in gateway.review_prompts[0]
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_exam_generator_extracts_choices_embedded_in_question_text() -> None:
    request_text = "出1道单选题，只要答案，不要解析，仅课程资料"
    plan = build_exam_plan(request_text, allow_external=False)
    question = _question(1)
    question.update(
        {
            "question_type": "single_choice",
            "prompt": (
                "栈遵循哪一种访问次序？\n"
                "A. 后进先出\nB. 先进先出\nC. 随机访问\nD. 按优先级访问"
            ),
            "options": [],
            "answer": "A",
            "explanation": None,
        }
    )
    gateway = ExamGateway(_payload(question))

    result = await GroundedExamGenerator(gateway).generate(
        request=request_text,
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert "- A. 后进先出" in result.answer.answer
    assert "- D. 按优先级访问" in result.answer.answer
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_exam_generator_retries_short_choice_list_until_batch_is_valid() -> None:
    request_text = "出1道单选题，只要答案，不要解析，仅课程资料"
    plan = build_exam_plan(request_text, allow_external=False)
    incomplete = _question(1)
    incomplete.update(
        {
            "question_type": "single_choice",
            "prompt": "栈遵循哪一种访问次序？",
            "options": ["后进先出", "先进先出", "随机访问"],
            "answer": "A",
            "explanation": None,
        }
    )
    repaired = {
        **incomplete,
        "options": ["后进先出", "先进先出", "随机访问", "按优先级访问"],
    }
    gateway = ExamGateway(_payload(incomplete), _payload(repaired))

    result = await GroundedExamGenerator(gateway).generate(
        request=request_text,
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert "- D. 按优先级访问" in result.answer.answer
    assert gateway.calls == 3


@pytest.mark.asyncio
async def test_exam_generator_bounds_repeated_invalid_choice_retries() -> None:
    request_text = "出1道单选题，只要答案，不要解析，仅课程资料"
    plan = build_exam_plan(request_text, allow_external=False)
    incomplete = _question(1)
    incomplete.update(
        {
            "question_type": "single_choice",
            "prompt": "栈遵循哪一种访问次序？",
            "options": ["后进先出", "先进先出", "随机访问"],
            "answer": "A",
            "explanation": None,
        }
    )
    gateway = ExamGateway(*[_payload(incomplete) for _ in range(4)])

    with pytest.raises(LLMOutputError, match="3 次局部修复.*选择项少于 4 个"):
        await GroundedExamGenerator(gateway).generate(
            request=request_text,
            plan=plan,
            course_hits=[_course_hit(1)],
            external_evidence=[],
            model="deepseek-v4-flash",
        )

    assert gateway.calls == 4


@pytest.mark.asyncio
async def test_exam_generator_retries_missing_source_in_same_batch() -> None:
    request_text = "出1道判断题，只要答案，不要解析，仅课程资料"
    plan = build_exam_plan(request_text, allow_external=False)
    missing_source = _question(1)
    missing_source["course_source_ids"] = []
    repaired = {**missing_source, "course_source_ids": [1]}
    gateway = ExamGateway(_payload(missing_source), _payload(repaired))

    result = await GroundedExamGenerator(gateway).generate(
        request=request_text,
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.answer.used_source_ids == (1,)
    assert gateway.calls == 3


@pytest.mark.asyncio
async def test_exam_generator_retries_and_normalizes_grounding_review_json() -> None:
    plan = build_exam_plan(
        "出1道判断题，只要答案，不要解析，仅课程资料",
        allow_external=False,
    )
    gateway = ExamGateway(
        _payload(_question(1)),
        review_contents=[
            "not json",
            (
                "```json\n"
                '{"reviews":[{"number":1,"supported":true,'
                '"unsupported_claim":null}]}\n'
                "```"
            ),
        ],
    )

    result = await GroundedExamGenerator(gateway).generate(
        request="出1道判断题，只要答案，不要解析，仅课程资料",
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.quality.grounding_verified is True
    assert gateway.calls == 3


async def test_exam_generator_mixes_external_within_cap_and_persists_diagnostics() -> None:
    plan = build_exam_plan("共5题，5道判断题", allow_external=True)
    gateway = ExamGateway(
        _payload(
            _question(1),
            _question(2),
            _question(3, external=True),
            _question(4),
        ),
        _payload(_question(5)),
    )

    result = await GroundedExamGenerator(gateway).generate(
        request="共5题，5道判断题",
        plan=plan,
        course_hits=[_course_hit(1), _course_hit(2, exercise=True)],
        external_evidence=[_external()],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.quality.generated_question_count == 5
    assert result.quality.external_supplement_count == 1
    assert result.quality.external_supplement_count <= result.quality.max_external_count
    assert result.answer.used_external_source_ids == (1,)
    assert "外部优质题材补充 [外1]" in result.answer.answer
    assert gateway.calls == 3


async def test_exam_generator_repairs_direct_textbook_adoption_over_30_percent() -> None:
    plan = build_exam_plan("共3题，3道判断题，仅课程", allow_external=False)
    adapted_prompt = "判断：栈中元素的插入和删除只能在栈顶进行。"
    gateway = ExamGateway(
        _payload(
            _question(1, prompt=adapted_prompt),
            _question(2),
            _question(3),
        ),
        _payload(_question(1, prompt="判断：栈遵循后进先出原则。")),
    )

    result = await GroundedExamGenerator(gateway).generate(
        request="共3题，3道判断题，仅课程",
        plan=plan,
        course_hits=[_course_hit(1), _course_hit(2, exercise=True)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.quality.course_adapted_count == 0
    assert result.quality.grounding_repaired_questions == [1]
    assert gateway.calls == 4


async def test_exam_generator_safely_degrades_when_external_search_has_no_results() -> None:
    plan = build_exam_plan("共5题，5道判断题", allow_external=True)
    gateway = ExamGateway(
        _payload(_question(1), _question(2), _question(3), _question(4)),
        _payload(_question(5)),
    )

    result = await GroundedExamGenerator(gateway).generate(
        request="共5题，5道判断题",
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.quality.external_fallback_applied is True
    assert result.quality.external_supplement_count == 0
    assert result.answer.used_external_source_ids == ()


async def test_exam_generator_normalizes_safe_real_model_json_variants() -> None:
    plan = build_exam_plan("出1道判断题，仅课程", allow_external=False)
    raw_question = _question(1)
    raw_question.update(
        {
            "options": None,
            "answer": True,
            "source_mode": "course",
            "course_source_ids": ["课1"],
            "constraints": None,
            "samples": None,
            "test_case_design": None,
        }
    )
    gateway = ExamGateway(_payload(raw_question))

    result = await GroundedExamGenerator(gateway).generate(
        request="出1道判断题，仅课程",
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert "**答案：** 正确" in result.answer.answer
    assert result.answer.used_source_ids == (1,)
    assert result.quality.passed is True


async def test_exam_generator_repairs_only_questions_rejected_by_grounding_review() -> None:
    plan = build_exam_plan("出1道判断题，仅课程", allow_external=False)
    gateway = ExamGateway(
        _payload(
            _question(
                1,
                prompt="判断：顺序队列出队时一定需要移动全部剩余元素。",
            )
        ),
        _payload(_question(1, prompt="判断：栈只在栈顶插入和删除。")),
        review_contents=[
            json.dumps(
                {
                    "results": [
                        {
                            "number": 1,
                            "supported": False,
                            "unsupported_claim": "课程来源没有说明顺序队列出队。",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            '{"results":[{"number":1,"supported":true}]}',
        ],
    )

    result = await GroundedExamGenerator(gateway).generate(
        request="出1道判断题，仅课程",
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.quality.grounding_repaired_questions == [1]
    assert "栈只在栈顶插入和删除" in result.answer.answer
    assert "顺序队列" not in result.answer.answer
    assert gateway.calls == 4


@pytest.mark.asyncio
async def test_exam_generator_rechecks_duplicates_after_one_repair_round() -> None:
    plan = build_exam_plan(
        "出2道判断题，只要答案，不要解析，仅课程资料",
        allow_external=False,
    )
    duplicate_prompt = "判断：栈只允许在栈顶插入和删除。"
    gateway = ExamGateway(
        _payload(
            _question(1, prompt=duplicate_prompt),
            _question(2, prompt=duplicate_prompt),
        ),
        _payload(_question(2, prompt="判断：读取栈顶元素不会改变栈顶位置。")),
    )

    result = await GroundedExamGenerator(gateway).generate(
        request="出2道判断题，只要答案，不要解析，仅课程资料",
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.quality.grounding_repaired_questions == [2]
    assert "读取栈顶元素不会改变栈顶位置" in result.answer.answer
    assert result.quality.duplicates_detected is False
    assert gateway.calls == 4


@pytest.mark.asyncio
async def test_exam_generator_returns_warned_exam_after_duplicate_repair_exhaustion() -> None:
    plan = build_exam_plan(
        "出2道判断题，只要答案，不要解析，仅课程资料",
        allow_external=False,
    )
    duplicate_prompt = "判断：栈只允许在栈顶插入和删除。"
    gateway = ExamGateway(
        _payload(
            _question(1, prompt=duplicate_prompt),
            _question(2, prompt=duplicate_prompt),
        ),
        _payload(_question(2, prompt=duplicate_prompt)),
    )

    result = await GroundedExamGenerator(gateway).generate(
        request="出2道判断题，只要答案，不要解析，仅课程资料",
        plan=plan,
        course_hits=[_course_hit(1)],
        external_evidence=[],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.ANSWERED
    assert result.quality.duplicates_detected is True
    assert result.quality.duplicate_question_numbers == [2]
    assert result.quality.passed is False
    assert result.quality.grounding_verified is True
    assert gateway.calls == 4


async def test_exam_generator_abstains_without_course_material() -> None:
    plan = build_exam_plan("出5道题", allow_external=True)
    gateway = ExamGateway()

    result = await GroundedExamGenerator(gateway).generate(
        request="出5道题",
        plan=plan,
        course_hits=[],
        external_evidence=[_external()],
        model="deepseek-v4-flash",
    )

    assert result.answer.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.quality.generated_question_count == 0
    assert gateway.calls == 0
