from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from httpx import ASGITransport, AsyncClient, Response

from app.core.config import Settings, get_settings
from app.evaluation import (
    MAX_AUDIT_TOKEN_BUDGET,
    BudgetedChatCompletionGateway,
    BudgetedExternalSearchGateway,
    BudgetExceededError,
    EvaluationCase,
    EvaluationDataset,
    EvaluationRunStore,
    EvaluationSplit,
    TokenBudgetLedger,
    aggregate_results,
    dataset_summary,
    evaluate_response,
    load_evaluation_dataset,
    load_human_annotations,
    load_judge_results,
    merge_review_layers,
    write_json_atomic,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATASET = _REPO_ROOT / "backend" / "evaluations" / "week05" / "dataset-v1.json"
_DEFAULT_OUTPUT = _REPO_ROOT / "output" / "week-05" / "day-01" / "m0"
_RUNTIME_PATHS = (
    "backend/app/api/routes/qa.py",
    "backend/app/core/config.py",
    "backend/app/external_search",
    "backend/app/generation",
    "backend/app/indexing",
    "backend/app/knowledge",
    "backend/app/orchestration",
    "backend/app/retrieval",
    "backend/app/schemas/qa.py",
    "backend/app/services/conversation.py",
    "backend/pyproject.toml",
    "backend/uv.lock",
)


def _sqlite_path(database_url: str) -> Path:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("week-five evaluation expects the local SQLite database")
    path = Path(database_url.removeprefix(prefix))
    return (Path.cwd() / path).resolve()


def _course_snapshot(
    database_url: str,
    *,
    requested_course_id: str | None,
    expected_course_name: str,
) -> tuple[UUID, str, list[dict[str, Any]]]:
    condition = "AND c.id = ?" if requested_course_id else "AND c.name = ?"
    requested = UUID(requested_course_id).hex if requested_course_id else expected_course_name
    query = f"""
        SELECT c.id, c.name, d.id, d.original_name, d.file_type, d.file_size,
               d.sha256, d.status, d.updated_at
        FROM courses AS c
        JOIN documents AS d ON d.course_id = c.id AND d.status = 'completed'
        WHERE 1 = 1 {condition}
        ORDER BY d.original_name, d.id
    """
    with sqlite3.connect(_sqlite_path(database_url)) as connection:
        rows = connection.execute(query, (requested,)).fetchall()
    if not rows:
        raise RuntimeError("no matching course with completed documents was found")
    course_ids = {str(row[0]) for row in rows}
    course_names = {str(row[1]) for row in rows}
    if len(course_ids) != 1 or course_names != {expected_course_name}:
        raise RuntimeError("evaluation course identity does not match the dataset")
    documents = [
        {
            "id": str(UUID(str(row[2]))),
            "original_name": str(row[3]),
            "file_type": str(row[4]),
            "file_size": int(row[5]),
            "sha256": str(row[6]),
            "status": str(row[7]),
            "updated_at": str(row[8]),
        }
        for row in rows
    ]
    return UUID(next(iter(course_ids))), next(iter(course_names)), documents


def _git_commit() -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={_REPO_ROOT.as_posix()}",
            "rev-parse",
            "HEAD",
        ],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"cannot resolve git baseline: {result.stderr.strip()}")
    return result.stdout.strip()


def _runtime_fingerprint() -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for relative in _RUNTIME_PATHS:
        path = _REPO_ROOT / relative
        files.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    for path in sorted(set(files)):
        digest.update(path.relative_to(_REPO_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _settings_snapshot(settings: Settings) -> dict[str, Any]:
    keys = (
        "llm_provider",
        "llm_base_url",
        "llm_model",
        "llm_max_output_tokens",
        "llm_temperature",
        "rag_answer_top_k",
        "rag_answer_candidate_k",
        "rag_summary_top_k",
        "rag_summary_candidate_k",
        "rag_summary_max_sources",
        "rag_summary_context_max_chars",
        "rag_exam_top_k",
        "rag_exam_candidate_k",
        "rag_exam_max_sources",
        "rag_exam_context_max_chars",
        "rag_min_similarity_score",
        "rag_context_max_messages",
        "rag_context_max_chars",
        "external_search_enabled",
        "external_search_max_uses",
        "external_search_max_results",
        "external_search_trigger_score",
        "qdrant_collection_name",
        "embedding_model_path",
        "embedding_device",
        "reranker_model_path",
        "reranker_device",
        "reranker_max_length",
    )
    payload: dict[str, Any] = {}
    for key in keys:
        value = getattr(settings, key)
        payload[key] = str(value) if isinstance(value, Path) else value
    return payload


def _manifest(
    *,
    dataset: EvaluationDataset,
    dataset_hash: str,
    settings: Settings,
    course_id: UUID,
    course_name: str,
    documents: list[dict[str, Any]],
    model: str,
) -> dict[str, Any]:
    actual_commit = _git_commit()
    if not actual_commit.startswith(dataset.baseline.git_commit):
        raise RuntimeError(
            f"current commit {actual_commit} is not approved baseline "
            f"{dataset.baseline.git_commit}"
        )
    settings_payload = _settings_snapshot(settings)
    if settings.rag_context_max_messages != dataset.baseline.context_max_messages:
        raise RuntimeError("M0 context message limit differs from the frozen dataset")
    if settings.rag_context_max_chars != dataset.baseline.context_max_chars:
        raise RuntimeError("M0 context character limit differs from the frozen dataset")
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline": dataset.baseline.model_dump(mode="json"),
        "actual_git_commit": actual_commit,
        "runtime_fingerprint_sha256": _runtime_fingerprint(),
        "dataset": {**dataset_summary(dataset), "sha256": dataset_hash},
        "course": {
            "id": str(course_id),
            "name": course_name,
            "completed_document_count": len(documents),
            "documents": documents,
        },
        "model": model,
        "random_seed": 20260810,
        "settings": settings_payload,
        "contains_secrets": False,
    }


async def _create_conversation(
    client: AsyncClient,
    *,
    course_id: UUID,
    case_id: str,
) -> str:
    response = await client.post(
        f"/api/courses/{course_id}/conversations",
        json={"title": f"第五周 M0 评测：{case_id}"},
    )
    _raise_for_api_error(response)
    return str(response.json()["data"]["id"])


async def _answer_turn(
    client: AsyncClient,
    *,
    course_id: UUID,
    conversation_id: str,
    question: str,
    answer_scope: str,
    model: str,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/courses/{course_id}/answers",
        json={
            "question": question,
            "answer_scope": answer_scope,
            "conversation_id": conversation_id,
            "model": model,
        },
    )
    _raise_for_api_error(response)
    data = response.json().get("data")
    if not isinstance(data, dict):
        raise RuntimeError("answer API returned an invalid data object")
    return dict(data)


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


def _raise_for_api_error(response: Response) -> None:
    if response.status_code < 400:
        return
    try:
        body: object = response.json()
    except ValueError:
        body = response.text[:1000]
    raise RuntimeError(f"HTTP {response.status_code}: {body}")


def _turn_summary(index: int, response: dict[str, Any]) -> dict[str, Any]:
    answer = str(response.get("answer") or "")
    return {
        "turn": index,
        "status": response.get("status"),
        "task_type": response.get("task_type"),
        "answer_chars": len(answer),
        "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
        "citation_count": len(response.get("citations") or []),
        "elapsed_ms": response.get("elapsed_ms"),
        "usage": response.get("usage"),
    }


def _case_result(
    case: EvaluationCase,
    *,
    response: dict[str, Any],
    turn_summaries: list[dict[str, Any]],
    started_at: datetime,
    finished_at: datetime,
    budget_before: dict[str, Any],
    budget_after: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "case_id": case.id,
        "split": case.split.value,
        "category": case.category.value,
        "partition_key": case.partition_key,
        "execution_status": "completed",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "turns": case.turns,
        "answer_scope": case.answer_scope,
        "expected": case.expected.model_dump(mode="json"),
        "response": response,
        "turn_summaries": turn_summaries,
        "metrics": evaluate_response(case, response),
        "budget_delta": {
            "accounted_tokens": (
                int(budget_after["accounted_tokens"])
                - int(budget_before["accounted_tokens"])
            ),
            "reported_tokens": (
                int(budget_after["reported_tokens"])
                - int(budget_before["reported_tokens"])
            ),
            "call_count": int(budget_after["call_count"]) - int(budget_before["call_count"]),
        },
        "human_review": None,
        "llm_judge": None,
    }


def _failed_case_result(
    case: EvaluationCase,
    *,
    started_at: datetime,
    error: Exception,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "case_id": case.id,
        "split": case.split.value,
        "category": case.category.value,
        "partition_key": case.partition_key,
        "execution_status": "failed",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "turns": case.turns,
        "answer_scope": case.answer_scope,
        "expected": case.expected.model_dump(mode="json"),
        "error_type": type(error).__name__,
        "error": str(error)[:2000],
        "human_review": None,
        "llm_judge": None,
    }


def _should_run_case(
    existing: dict[str, Any] | None,
    *,
    rerun_failed: bool,
) -> bool:
    if existing is None:
        return True
    return rerun_failed and existing.get("execution_status") == "failed"


def _write_reports(
    output_dir: Path,
    *,
    manifest: dict[str, Any],
    ledger: TokenBudgetLedger,
    results: list[dict[str, Any]],
    stopped_reason: str | None,
) -> None:
    ordered = sorted(results, key=lambda item: str(item.get("case_id")))
    overall = aggregate_results(ordered)
    by_split = {
        split.value: aggregate_results(
            item for item in ordered if item.get("split") == split.value
        )
        for split in EvaluationSplit
    }
    categories = sorted({str(item.get("category")) for item in ordered})
    by_category = {
        category: aggregate_results(
            item for item in ordered if item.get("category") == category
        )
        for category in categories
    }
    budget_payload: dict[str, Any] = asdict(ledger.snapshot())
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest": manifest,
        "budget": budget_payload,
        "stopped_reason": stopped_reason,
        "overall": overall,
        "by_split": by_split,
        "by_category": by_category,
        "results": ordered,
        "review_layers": {
            "deterministic_metrics": "populated",
            "human_annotations": "separate file; pending",
            "llm_as_judge": "separate file; not run",
        },
    }
    write_json_atomic(output_dir / "report.json", payload)
    lines = [
        "# 第五周计划日 1：M0 评测报告",
        "",
        f"- 基线：{manifest['baseline']['name']} / {manifest['actual_git_commit']}",
        f"- 数据集：{manifest['dataset']['dataset_id']} {manifest['dataset']['version']}",
        (
            f"- 课程：{manifest['course']['name']}"
            f"（{manifest['course']['completed_document_count']} 份资料）"
        ),
        f"- 模型：{manifest['model']}",
        f"- 已完成：{overall['completed_case_count']}/{manifest['dataset']['case_count']}",
        f"- 结构指标通过率：{_format_rate(overall['structural_pass_rate'])}",
        (
            f"- 保守计入 token：{budget_payload['accounted_tokens']}"
            f"/{budget_payload['limit_tokens']}"
        ),
        f"- 上游报告 token：{budget_payload['reported_tokens']}",
        "- 人工标注与 LLM-as-Judge 均为独立层；本报告未用 Judge 覆盖人工结论。",
        "",
        "| ID | Split | 类型 | 状态 | 结构检查 | 引用 | 耗时 | Token |",
        "|---|---|---|---|---|---:|---:|---:|",
    ]
    for item in ordered:
        raw_metrics = item.get("metrics")
        raw_response = item.get("response")
        metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
        response: dict[str, Any] = raw_response if isinstance(raw_response, dict) else {}
        lines.append(
            f"| {item.get('case_id')} | {item.get('split')} | {item.get('category')} | "
            f"{item.get('execution_status')} | "
            f"{'通过' if metrics.get('structural_pass') else '-'} | "
            f"{metrics.get('citation_count', 0)} | {response.get('elapsed_ms', '-')} | "
            f"{metrics.get('reported_tokens', 0)} |"
        )
    if stopped_reason:
        lines.extend(["", f"> 提前停止：{stopped_reason}"])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_rate(value: object) -> str:
    return f"{value:.1%}" if isinstance(value, (int, float)) else "-"


def _export_annotations(
    dataset: EvaluationDataset,
    dataset_hash: str,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    annotations = {
        "schema_version": "1.0",
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.version,
        "dataset_sha256": dataset_hash,
        "instructions": (
            "candidate answers are suggestions only; fill reference_answer and set "
            "review_status=verified after human review"
        ),
        "cases": [
            {
                "case_id": case.id,
                "review_status": "pending",
                "reference_answer": "",
                "key_points": [],
                "reviewer": None,
                "reviewed_at": None,
                "notes": "",
            }
            for case in dataset.cases
        ],
    }
    write_json_atomic(output_dir / "human-annotations.json", annotations)
    lines = [
        "# 第五周 100 条评测集人工标注表",
        "",
        f"- 数据集：`{dataset.dataset_id}` / `{dataset.version}`",
        f"- SHA-256：`{dataset_hash}`",
        "- 下列答案均为候选草稿，不会作为提示发送给被评测模型。",
        "- 审核时可直接修改候选答案，并填写“人工结论”。",
        "",
    ]
    for case in dataset.cases:
        lines.extend(
            [
                f"## {case.id} · {case.split.value} · {case.category.value}",
                "",
                f"- 隔离分区：`{case.partition_key}`",
                f"- 问题：{' → '.join(case.turns)}",
                f"- 预期状态：`{case.expected.status}`",
                f"- 候选参考答案：{case.expected.candidate_answer}",
                f"- 候选得分点：{'；'.join(case.expected.key_points) or '无'}",
                f"- 候选资料定位：{'；'.join(case.expected.source_targets) or '无'}",
                "- 人工结论：待填写",
                "",
            ]
        )
    (output_dir / "annotation-review.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


async def _run(arguments: argparse.Namespace) -> int:
    from app.external_search import (
        DeepSeekWebSearchAdapter,
        get_external_search_gateway,
    )
    from app.generation import OpenAICompatibleChatClient, get_chat_completion_gateway
    from app.main import app

    settings = get_settings()
    dataset, dataset_hash = load_evaluation_dataset(Path(arguments.dataset))
    selected = dataset.select(
        splits={EvaluationSplit(item) for item in arguments.split} if arguments.split else None,
        case_ids=set(arguments.case) if arguments.case else None,
        limit=arguments.limit,
    )
    if not selected:
        raise ValueError("no evaluation cases were selected")
    if not settings.llm_api_key.strip():
        raise RuntimeError("LLM_API_KEY is not configured")
    model = arguments.model or settings.llm_model
    course_id, course_name, documents = _course_snapshot(
        settings.database_url,
        requested_course_id=arguments.course_id,
        expected_course_name=dataset.course_name,
    )
    output_dir = Path(arguments.output_dir).resolve()
    manifest = _manifest(
        dataset=dataset,
        dataset_hash=dataset_hash,
        settings=settings,
        course_id=course_id,
        course_name=course_name,
        documents=documents,
        model=model,
    )
    ledger_path = Path(arguments.ledger).resolve()
    ledger = TokenBudgetLedger(limit_tokens=arguments.token_budget, path=ledger_path)
    store = EvaluationRunStore(output_dir)
    identity = {
        "dataset_sha256": dataset_hash,
        "baseline_commit": dataset.baseline.git_commit,
        "runtime_fingerprint_sha256": manifest["runtime_fingerprint_sha256"],
        "course_id": str(course_id),
        "document_sha256": [item["sha256"] for item in documents],
        "model": model,
        "token_budget": arguments.token_budget,
    }
    store.initialize(identity)
    write_json_atomic(output_dir / "baseline-manifest.json", manifest)
    chat = BudgetedChatCompletionGateway(
        OpenAICompatibleChatClient(settings),
        ledger,
        max_output_tokens=settings.llm_max_output_tokens,
    )
    external = BudgetedExternalSearchGateway(DeepSeekWebSearchAdapter(settings), ledger)
    app.dependency_overrides[get_chat_completion_gateway] = lambda: chat
    app.dependency_overrides[get_external_search_gateway] = lambda: external
    stopped_reason: str | None = None
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://evaluation") as client:
            for case in selected:
                existing = store.result(case.id)
                if not _should_run_case(existing, rerun_failed=arguments.rerun_failed):
                    continue
                conversation_id: str | None = None
                started_at = datetime.now(UTC)
                before = asdict(ledger.snapshot())
                try:
                    conversation_id = await _create_conversation(
                        client, course_id=course_id, case_id=case.id
                    )
                    responses: list[dict[str, Any]] = []
                    for turn in case.turns:
                        responses.append(
                            await _answer_turn(
                                client,
                                course_id=course_id,
                                conversation_id=conversation_id,
                                question=turn,
                                answer_scope=case.answer_scope,
                                model=model,
                            )
                        )
                    after = asdict(ledger.snapshot())
                    result = _case_result(
                        case,
                        response=responses[-1],
                        turn_summaries=[
                            _turn_summary(index, response)
                            for index, response in enumerate(responses, start=1)
                        ],
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                        budget_before=before,
                        budget_after=after,
                    )
                    store.write_case_result(case.id, result)
                except BudgetExceededError as error:
                    stopped_reason = str(error)
                    store.set_stopped_reason(stopped_reason)
                    break
                except Exception as error:
                    store.write_case_result(
                        case.id,
                        _failed_case_result(case, started_at=started_at, error=error),
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
                            if stopped_reason is None:
                                stopped_reason = (
                                    f"temporary conversation cleanup failed for {case.id}: "
                                    f"{cleanup_error}"
                                )
                _write_reports(
                    output_dir,
                    manifest=manifest,
                    ledger=ledger,
                    results=store.results(),
                    stopped_reason=stopped_reason,
                )
                if stopped_reason:
                    break
    finally:
        app.dependency_overrides.pop(get_chat_completion_gateway, None)
        app.dependency_overrides.pop(get_external_search_gateway, None)
    store.set_stopped_reason(stopped_reason)
    _write_reports(
        output_dir,
        manifest=manifest,
        ledger=ledger,
        results=store.results(),
        stopped_reason=stopped_reason,
    )
    print(
        json.dumps(
            {
                "selected": len(selected),
                "results": len(store.results()),
                "budget": asdict(ledger.snapshot()),
                "stopped_reason": stopped_reason,
            },
            ensure_ascii=False,
        )
    )
    final_results = store.results()
    if stopped_reason:
        return 2
    return 1 if any(item.get("execution_status") == "failed" for item in final_results) else 0


def _validate(arguments: argparse.Namespace) -> int:
    dataset, dataset_hash = load_evaluation_dataset(Path(arguments.dataset))
    summary = dataset_summary(dataset)
    expected_counts = {
        "course_qa": 25,
        "refusal": 10,
        "mixed_source": 15,
        "dynamic_summary": 10,
        "mixed_exam": 10,
        "multi_turn": 20,
        "course_isolation": 10,
    }
    if summary["case_count"] != 100:
        raise ValueError("week-five dataset must contain exactly 100 cases")
    if summary["split_counts"] != {"train": 60, "validation": 20, "test": 20}:
        raise ValueError("week-five dataset split must be 60/20/20")
    if summary["category_counts"] != expected_counts:
        raise ValueError("week-five dataset category distribution differs from the plan")
    print(json.dumps({**summary, "sha256": dataset_hash}, ensure_ascii=False, indent=2))
    return 0


def _export(arguments: argparse.Namespace) -> int:
    dataset, dataset_hash = load_evaluation_dataset(Path(arguments.dataset))
    _export_annotations(dataset, dataset_hash, Path(arguments.output_dir).resolve())
    return 0


def _snapshot(arguments: argparse.Namespace) -> int:
    settings = get_settings()
    dataset, dataset_hash = load_evaluation_dataset(Path(arguments.dataset))
    course_id, course_name, documents = _course_snapshot(
        settings.database_url,
        requested_course_id=arguments.course_id,
        expected_course_name=dataset.course_name,
    )
    manifest = _manifest(
        dataset=dataset,
        dataset_hash=dataset_hash,
        settings=settings,
        course_id=course_id,
        course_name=course_name,
        documents=documents,
        model=arguments.model or settings.llm_model,
    )
    output_dir = Path(arguments.output_dir).resolve()
    write_json_atomic(output_dir / "baseline-manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _review(arguments: argparse.Namespace) -> int:
    dataset, dataset_hash = load_evaluation_dataset(Path(arguments.dataset))
    known_case_ids = {case.id for case in dataset.cases}
    report_path = Path(arguments.report).resolve()
    raw_report: Any = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(raw_report, dict):
        raise ValueError("evaluation report must be a JSON object")
    raw_results = raw_report.get("results")
    if not isinstance(raw_results, list) or not all(
        isinstance(item, dict) for item in raw_results
    ):
        raise ValueError("evaluation report does not contain case results")
    human = load_human_annotations(
        Path(arguments.human_annotations).resolve(),
        dataset_sha256=dataset_hash,
        known_case_ids=known_case_ids,
    )
    judge = (
        load_judge_results(
            Path(arguments.judge_results).resolve(),
            dataset_sha256=dataset_hash,
            known_case_ids=known_case_ids,
        )
        if arguments.judge_results
        else None
    )
    result_dicts = [dict(item) for item in raw_results]
    merged = merge_review_layers(result_dicts, human=human, judge=judge)
    raw_report["results"] = merged
    raw_report["overall"] = aggregate_results(merged)
    raw_report["by_split"] = {
        split.value: aggregate_results(
            item for item in merged if item.get("split") == split.value
        )
        for split in EvaluationSplit
    }
    categories = sorted({str(item.get("category")) for item in merged})
    raw_report["by_category"] = {
        category: aggregate_results(
            item for item in merged if item.get("category") == category
        )
        for category in categories
    }
    raw_report["review_layers"] = {
        "human_annotations": str(Path(arguments.human_annotations).resolve()),
        "verified_human_count": raw_report["overall"]["human_reviewed_count"],
        "llm_judge_results": (
            str(Path(arguments.judge_results).resolve())
            if arguments.judge_results
            else None
        ),
        "llm_judged_count": raw_report["overall"]["llm_judged_count"],
        "precedence": "human review is authoritative; judge results remain advisory",
    }
    write_json_atomic(Path(arguments.output).resolve(), raw_report)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, annotate and run the frozen week-five M0 evaluation"
    )
    parser.add_argument("--dataset", default=str(_DEFAULT_DATASET))
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    export = subparsers.add_parser("export-annotations")
    export.add_argument(
        "--output-dir",
        default=str(_REPO_ROOT / "output" / "week-05" / "day-01" / "annotations"),
    )
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--output-dir", default=str(_DEFAULT_OUTPUT))
    snapshot.add_argument("--course-id")
    snapshot.add_argument("--model")
    review = subparsers.add_parser("review")
    review.add_argument("--report", required=True)
    review.add_argument("--human-annotations", required=True)
    review.add_argument("--judge-results")
    review.add_argument("--output", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--output-dir", default=str(_DEFAULT_OUTPUT))
    run.add_argument(
        "--ledger",
        default=str(_DEFAULT_OUTPUT / "token-ledger.json"),
    )
    run.add_argument(
        "--token-budget",
        type=int,
        default=MAX_AUDIT_TOKEN_BUDGET,
        metavar=f"1..{MAX_AUDIT_TOKEN_BUDGET}",
    )
    run.add_argument("--course-id")
    run.add_argument("--model")
    run.add_argument("--split", action="append", choices=[item.value for item in EvaluationSplit])
    run.add_argument("--case", action="append")
    run.add_argument("--limit", type=int)
    run.add_argument("--rerun-failed", action="store_true")
    return parser


def main() -> None:
    parser = _parser()
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate":
            code = _validate(arguments)
        elif arguments.command == "export-annotations":
            code = _export(arguments)
        elif arguments.command == "snapshot":
            code = _snapshot(arguments)
        elif arguments.command == "review":
            code = _review(arguments)
        else:
            if arguments.limit is not None and arguments.limit < 1:
                parser.error("--limit must be positive")
            if not 1 <= arguments.token_budget <= MAX_AUDIT_TOKEN_BUDGET:
                parser.error(
                    f"--token-budget must be between 1 and {MAX_AUDIT_TOKEN_BUDGET}"
                )
            code = asyncio.run(_run(arguments))
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
    raise SystemExit(code)


if __name__ == "__main__":
    main()
