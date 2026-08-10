from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from httpx import ASGITransport, AsyncClient, Response

from app.core.config import get_settings
from app.evaluation import (
    MAX_AUDIT_TOKEN_BUDGET,
    BudgetedChatCompletionGateway,
    BudgetedExternalSearchGateway,
    BudgetExceededError,
    TokenBudgetLedger,
)
from app.external_search import DeepSeekWebSearchAdapter, get_external_search_gateway
from app.generation import OpenAICompatibleChatClient, get_chat_completion_gateway
from app.main import app


@dataclass(frozen=True, slots=True)
class AuditCase:
    key: str
    request: str
    expected_task_type: str
    answer_scope: str
    use_stream: bool = False
    expected_question_count: int | None = None
    expected_answers: bool | None = None
    expected_explanations: bool | None = None
    follow_up_request: str | None = None
    initial_answers: bool | None = None
    initial_explanations: bool | None = None


_CASES = (
    AuditCase(
        key="course_only_question",
        request="栈的基本特点是什么？请根据课程资料回答。",
        expected_task_type="question",
        answer_scope="course_only",
    ),
    AuditCase(
        key="mixed_external_question",
        request=(
            "结合当前课程关于栈的内容与外部 C++ 标准库资料，"
            "说明 std::stack 与课程栈抽象的对应关系。"
        ),
        expected_task_type="question",
        answer_scope="course_and_external",
    ),
    AuditCase(
        key="engineering_summary",
        request="从工程取舍与可维护性的角度总结哈希表。",
        expected_task_type="summary",
        answer_scope="course_and_external",
    ),
    AuditCase(
        key="cpp_summary_stream",
        request=(
            "从 C++ 实现角度总结二叉树遍历，"
            "重点说明函数结构和容易写错的边界。"
        ),
        expected_task_type="summary",
        answer_scope="course_and_external",
        use_stream=True,
    ),
    AuditCase(
        key="questions_only_exam",
        request=(
            "请根据栈相关内容出一份仅含3道判断题的试卷，"
            "答案和解析都不要，仅课程资料。"
        ),
        expected_task_type="exam",
        answer_scope="course_and_external",
        expected_question_count=3,
        expected_answers=False,
        expected_explanations=False,
    ),
    AuditCase(
        key="answers_only_exam",
        request=(
            "请根据排序章节出一份仅含3道单选题的模拟卷，"
            "只要答案，暂时不用输出解析，仅课程资料。"
        ),
        expected_task_type="exam",
        answer_scope="course_and_external",
        expected_question_count=3,
        expected_answers=True,
        expected_explanations=False,
    ),
    AuditCase(
        key="default_output_choice_exam",
        request="请根据排序章节出一份仅含3道单选题的模拟卷。",
        expected_task_type="exam",
        answer_scope="course_and_external",
        expected_question_count=3,
        expected_answers=True,
        expected_explanations=True,
    ),
    AuditCase(
        key="contextual_exam_follow_up",
        request=(
            "请根据队列相关内容出一份仅含3道判断题的试卷，"
            "答案和解析都不要。"
        ),
        follow_up_request="现在给出答案和解析。",
        expected_task_type="exam",
        answer_scope="course_and_external",
        expected_question_count=3,
        expected_answers=True,
        expected_explanations=True,
        initial_answers=False,
        initial_explanations=False,
        use_stream=True,
    ),
)


def _sqlite_path(database_url: str) -> Path:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("The integration audit expects the local SQLite database.")
    return Path(database_url.removeprefix(prefix)).resolve()


def _ready_course(database_url: str, requested_course_id: str | None) -> tuple[UUID, str, int]:
    condition = "AND c.id = ?" if requested_course_id else ""
    parameters: tuple[str, ...] = (
        (UUID(requested_course_id).hex,) if requested_course_id else ()
    )
    query = f"""
        SELECT c.id, c.name, COUNT(d.id) AS ready_count
        FROM courses AS c
        JOIN documents AS d ON d.course_id = c.id AND d.status = 'completed'
        WHERE 1 = 1 {condition}
        GROUP BY c.id, c.name
        ORDER BY c.updated_at DESC
        LIMIT 1
    """
    with sqlite3.connect(_sqlite_path(database_url)) as connection:
        row = connection.execute(query, parameters).fetchone()
    if row is None:
        raise RuntimeError("No course with completed documents was found for the audit.")
    return UUID(str(row[0])), str(row[1]), int(row[2])


def _selected_cases(keys: list[str] | None) -> tuple[AuditCase, ...]:
    if not keys:
        return _CASES
    requested = set(keys)
    selected = tuple(case for case in _CASES if case.key in requested)
    missing = requested.difference(case.key for case in selected)
    if missing:
        raise ValueError(f"unknown audit cases: {', '.join(sorted(missing))}")
    return selected


async def _create_conversation(client: AsyncClient, course_id: UUID, key: str) -> str:
    response = await client.post(
        f"/api/courses/{course_id}/conversations",
        json={"title": f"第四周第五日审计：{key}"},
    )
    _raise_for_api_error(response)
    return str(response.json()["data"]["id"])


async def _answer_case(
    client: AsyncClient,
    *,
    course_id: UUID,
    conversation_id: str,
    case: AuditCase,
    model: str,
) -> dict[str, Any]:
    async def answer_once(question: str) -> dict[str, Any]:
        payload = {
            "question": question,
            "answer_scope": case.answer_scope,
            "conversation_id": conversation_id,
            "model": model,
        }
        if not case.use_stream:
            response = await client.post(
                f"/api/courses/{course_id}/answers",
                json=payload,
            )
            _raise_for_api_error(response)
            return dict(response.json()["data"])

        response = await client.post(
            f"/api/courses/{course_id}/answers/stream",
            json=payload,
        )
        _raise_for_api_error(response)
        events = _parse_sse(response.text)
        event_names = [name for name, _ in events]
        if "error" in event_names:
            error = next(data for name, data in events if name == "error")
            raise RuntimeError(str(error.get("message") or "stream audit failed"))
        required = {"start", "delta", "citations", "complete"}
        if not required.issubset(event_names):
            raise RuntimeError(f"stream events incomplete: {event_names}")
        complete = next(data for name, data in events if name == "complete")
        complete["audit_sse_events"] = event_names
        return complete

    initial = await answer_once(case.request)
    if case.follow_up_request is None:
        return initial
    initial_plan = (initial.get("retrieval") or {}).get("exam_plan") or {}
    if initial_plan.get("include_answers") is not case.initial_answers:
        raise RuntimeError("initial exam answer switch mismatch")
    if initial_plan.get("include_explanations") is not case.initial_explanations:
        raise RuntimeError("initial exam explanation switch mismatch")
    initial_answer = str(initial.get("answer") or "")
    if "**答案：**" in initial_answer or "**解析：**" in initial_answer:
        raise RuntimeError("initial questions-only exam leaked a hidden solution")

    result = await answer_once(case.follow_up_request)
    final_answer = str(result.get("answer") or "")
    if _exam_question_bodies(initial_answer) != _exam_question_bodies(final_answer):
        raise RuntimeError("follow-up did not preserve the exact same exam questions")
    result["audit_initial_turn"] = {
        "answer_chars": len(initial_answer),
        "answer_sha256": hashlib.sha256(initial_answer.encode("utf-8")).hexdigest(),
        "question_count": len(_exam_question_bodies(initial_answer)),
    }
    return result


def _exam_question_bodies(answer: str) -> tuple[str, ...]:
    return tuple(
        " ".join(match.group(1).split())
        for match in re.finditer(
            r"^##\s+\d+\..*?\n\n(.*?)(?=\n\n>\s*知识点：)",
            answer,
            flags=re.MULTILINE | re.DOTALL,
        )
    )


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        if name and data_lines:
            payload = json.loads("\n".join(data_lines))
            if isinstance(payload, dict):
                events.append((name, payload))
    return events


async def _verify_history(
    client: AsyncClient,
    *,
    course_id: UUID,
    conversation_id: str,
    expected_task_type: str,
    expected_turn_count: int = 1,
) -> dict[str, Any]:
    response = await client.get(
        f"/api/courses/{course_id}/conversations/{conversation_id}"
    )
    _raise_for_api_error(response)
    data = response.json()["data"]
    messages = data["messages"]
    expected_roles = ["user", "assistant"] * expected_turn_count
    if [item["role"] for item in messages] != expected_roles:
        raise RuntimeError(
            f"temporary audit conversation did not persist {expected_turn_count} turn(s)"
        )
    retrieval = messages[-1].get("retrieval") or {}
    if retrieval.get("task_type") != expected_task_type:
        raise RuntimeError("persisted task type differs from the live response")
    return {
        "message_count": len(messages),
        "persisted_task_type": retrieval.get("task_type"),
        "persisted_citation_count": len(messages[-1].get("citations") or []),
    }


def _validate_result(case: AuditCase, data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    retrieval = data.get("retrieval") or {}
    task_type = data.get("task_type")
    if task_type != case.expected_task_type:
        errors.append(f"task_type={task_type}, expected={case.expected_task_type}")
    if retrieval.get("task_type") != case.expected_task_type:
        errors.append("retrieval task type mismatch")
    if data.get("status") != "answered":
        errors.append(f"status={data.get('status')}")
    citations = data.get("citations") or []
    if not citations:
        errors.append("no verified citations")
    if case.expected_task_type == "summary":
        if data.get("answer_scope") != "course_only":
            errors.append("summary did not force course_only")
        if (data.get("external_search") or {}).get("triggered"):
            errors.append("summary unexpectedly triggered external search")
        quality = retrieval.get("summary_quality") or {}
        if not quality.get("passed"):
            errors.append("summary quality did not pass")
    if case.expected_task_type == "exam":
        plan = retrieval.get("exam_plan") or {}
        quality = retrieval.get("exam_quality") or {}
        expected = case.expected_question_count
        if plan.get("question_count") != expected:
            errors.append("exam plan question count mismatch")
        if quality.get("generated_question_count") != expected:
            errors.append("generated exam question count mismatch")
        if plan.get("include_answers") is not case.expected_answers:
            errors.append("exam answer switch mismatch")
        if plan.get("include_explanations") is not case.expected_explanations:
            errors.append("exam explanation switch mismatch")
        if not quality.get("citations_valid"):
            errors.append("exam citations invalid")
        if not quality.get("source_limits_passed"):
            errors.append("exam source limits failed")
        if not quality.get("grounding_verified"):
            errors.append("exam grounding review failed")
        if case.follow_up_request is not None:
            if retrieval.get("retrieval_mode") != "exam_artifact_replay":
                errors.append("exam follow-up did not replay the persisted artifact")
            answer = str(data.get("answer") or "")
            if answer.count("**答案：**") != case.expected_question_count:
                errors.append("exam follow-up answer count mismatch")
            if answer.count("**解析：**") != case.expected_question_count:
                errors.append("exam follow-up explanation count mismatch")
    return errors


def _safe_case_result(
    case: AuditCase,
    data: dict[str, Any],
    history: dict[str, Any],
    *,
    started_at: datetime,
) -> dict[str, Any]:
    answer = str(data.get("answer") or "")
    retrieval = data.get("retrieval") or {}
    citations = data.get("citations") or []
    return {
        "key": case.key,
        "request": case.request,
        "passed": True,
        "started_at": started_at.isoformat(),
        "task_type": data.get("task_type"),
        "status": data.get("status"),
        "answer_scope": data.get("answer_scope"),
        "model": data.get("model"),
        "elapsed_ms": data.get("elapsed_ms"),
        "answer_chars": len(answer),
        "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        "citation_count": len(citations),
        "course_citation_count": sum(
            item.get("source_type") == "course" for item in citations
        ),
        "external_citation_count": sum(
            item.get("source_type") == "external" for item in citations
        ),
        "external_search": data.get("external_search"),
        "summary_plan": retrieval.get("summary_plan"),
        "summary_quality": retrieval.get("summary_quality"),
        "exam_plan": retrieval.get("exam_plan"),
        "exam_quality": retrieval.get("exam_quality"),
        "usage": data.get("usage"),
        "sse_events": data.get("audit_sse_events"),
        "initial_turn": data.get("audit_initial_turn"),
        "history": history,
    }


def _raise_for_api_error(response: Response) -> None:
    if response.status_code < 400:
        return
    try:
        body = response.json()
    except ValueError:
        body = response.text[:500]
    raise RuntimeError(f"HTTP {response.status_code}: {body}")


async def _delete_conversation(
    client: AsyncClient,
    *,
    course_id: UUID,
    conversation_id: str,
) -> None:
    response = await client.delete(
        f"/api/courses/{course_id}/conversations/{conversation_id}"
    )
    _raise_for_api_error(response)


def _write_report(
    output_dir: Path,
    *,
    course_id: UUID,
    course_name: str,
    document_count: int,
    model: str,
    ledger: TokenBudgetLedger,
    cases: list[dict[str, Any]],
    stopped_reason: str | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = ledger.snapshot()
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "course_id": str(course_id),
        "course_name": course_name,
        "completed_document_count": document_count,
        "model": model,
        "contains_course_content": False,
        "budget": asdict(snapshot),
        "stopped_reason": stopped_reason,
        "passed": bool(cases) and all(item.get("passed") for item in cases),
        "cases": cases,
    }
    (output_dir / "audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# 第四周第五日真实课程集成审计",
        "",
        f"- 课程：{course_name}（{document_count} 份已完成资料）",
        f"- 模型：{model}",
        f"- 总体：{'通过' if payload['passed'] else '未通过'}",
        f"- 保守计入 token：{snapshot.accounted_tokens}/{snapshot.limit_tokens}",
        f"- 上游报告 token：{snapshot.reported_tokens}",
        f"- 剩余保守预算：{snapshot.remaining_tokens}",
        "- 报告不包含课程正文、完整回答、引用正文或 API Key。",
        "",
        "| 用例 | 任务 | 状态 | 引用 | 耗时 | 结果 |",
        "|---|---|---|---:|---:|---|",
    ]
    for item in cases:
        lines.append(
            f"| {item['key']} | {item.get('task_type', '-')} | "
            f"{item.get('status', '-')} | {item.get('citation_count', 0)} | "
            f"{item.get('elapsed_ms', '-')} ms | "
            f"{'通过' if item.get('passed') else '失败'} |"
        )
    if stopped_reason:
        lines.extend(["", f"> 提前停止：{stopped_reason}"])
    (output_dir / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _previous_results(output_dir: Path, selected_keys: set[str]) -> list[dict[str, Any]]:
    report_path = output_dir / "audit.json"
    if not selected_keys or not report_path.exists():
        return []
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        return []
    return [
        dict(item)
        for item in cases
        if isinstance(item, dict) and item.get("key") not in selected_keys
    ]


def _ordered_results(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {case.key: index for index, case in enumerate(_CASES)}
    return sorted(cases, key=lambda item: order.get(str(item.get("key")), len(order)))


async def _run(arguments: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.llm_api_key.strip():
        raise RuntimeError("LLM_API_KEY is not configured.")
    course_id, course_name, document_count = _ready_course(
        settings.database_url,
        arguments.course_id,
    )
    output_dir = Path(arguments.output_dir).resolve()
    ledger_path = Path(arguments.ledger).resolve()
    ledger = TokenBudgetLedger(limit_tokens=arguments.token_budget, path=ledger_path)
    chat = BudgetedChatCompletionGateway(
        OpenAICompatibleChatClient(settings),
        ledger,
        max_output_tokens=settings.llm_max_output_tokens,
    )
    external = BudgetedExternalSearchGateway(
        DeepSeekWebSearchAdapter(settings),
        ledger,
    )
    app.dependency_overrides[get_chat_completion_gateway] = lambda: chat
    app.dependency_overrides[get_external_search_gateway] = lambda: external
    selected_cases = _selected_cases(arguments.case)
    selected_keys = {case.key for case in selected_cases}
    results = _previous_results(output_dir, selected_keys)
    stopped_reason: str | None = None
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://audit") as client:
            for case in selected_cases:
                conversation_id: str | None = None
                started_at = datetime.now(UTC)
                try:
                    conversation_id = await _create_conversation(
                        client,
                        course_id,
                        case.key,
                    )
                    data = await _answer_case(
                        client,
                        course_id=course_id,
                        conversation_id=conversation_id,
                        case=case,
                        model=arguments.model or settings.llm_model,
                    )
                    errors = _validate_result(case, data)
                    if errors:
                        raise RuntimeError("; ".join(errors))
                    history = await _verify_history(
                        client,
                        course_id=course_id,
                        conversation_id=conversation_id,
                        expected_task_type=case.expected_task_type,
                        expected_turn_count=(2 if case.follow_up_request else 1),
                    )
                    results.append(
                        _safe_case_result(
                            case,
                            data,
                            history,
                            started_at=started_at,
                        )
                    )
                except BudgetExceededError as error:
                    stopped_reason = str(error)
                    break
                except Exception as error:
                    results.append(
                        {
                            "key": case.key,
                            "request": case.request,
                            "passed": False,
                            "started_at": started_at.isoformat(),
                            "error_type": type(error).__name__,
                            "error": str(error)[:1000],
                        }
                    )
                finally:
                    if conversation_id is not None:
                        try:
                            await _delete_conversation(
                                client,
                                course_id=course_id,
                                conversation_id=conversation_id,
                            )
                        except Exception as cleanup_error:
                            results.append(
                                {
                                    "key": f"{case.key}:cleanup",
                                    "passed": False,
                                    "error_type": type(cleanup_error).__name__,
                                    "error": str(cleanup_error)[:1000],
                                }
                            )
                _write_report(
                    output_dir,
                    course_id=course_id,
                    course_name=course_name,
                    document_count=document_count,
                    model=arguments.model or settings.llm_model,
                    ledger=ledger,
                    cases=_ordered_results(results),
                    stopped_reason=stopped_reason,
                )
    finally:
        app.dependency_overrides.pop(get_chat_completion_gateway, None)
        app.dependency_overrides.pop(get_external_search_gateway, None)
    _write_report(
        output_dir,
        course_id=course_id,
        course_name=course_name,
        document_count=document_count,
        model=arguments.model or settings.llm_model,
        ledger=ledger,
        cases=_ordered_results(results),
        stopped_reason=stopped_reason,
    )
    ordered_results = _ordered_results(results)
    print(
        json.dumps(
            {"budget": asdict(ledger.snapshot()), "cases": ordered_results},
            ensure_ascii=False,
        )
    )
    passed = (
        ordered_results
        and all(item.get("passed") for item in ordered_results)
        and not stopped_reason
    )
    return 0 if passed else 1


def _token_budget(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= MAX_AUDIT_TOKEN_BUDGET:
        raise argparse.ArgumentTypeError(
            f"token budget must be between 1 and {MAX_AUDIT_TOKEN_BUDGET}"
        )
    return parsed


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--course-id")
    parser.add_argument("--model")
    parser.add_argument("--case", action="append", choices=[case.key for case in _CASES])
    parser.add_argument("--token-budget", type=_token_budget, default=MAX_AUDIT_TOKEN_BUDGET)
    parser.add_argument(
        "--output-dir",
        default="../output/week-04/day-05",
    )
    parser.add_argument(
        "--ledger",
        default="../output/week-04/day-05/token-ledger.json",
    )
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
