from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from dataclasses import asdict, replace
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.external_search import (
    DeepSeekWebSearchAdapter,
    ExternalSearchEvidence,
    ExternalSearchStatus,
)
from app.generation import (
    GroundedExamGenerator,
    OpenAICompatibleChatClient,
    build_exam_plan,
)
from app.indexing.runtime import DocumentIndexingPipeline
from app.knowledge import VectorSearchResult

_SYNTHETIC_STACK_TEXTS = (
    "第三章介绍栈抽象数据类型。栈遵循后进先出原则，只允许在栈顶插入、删除和读取元素。",
    "顺序栈使用连续数组 data 和栈顶下标 top。初始化时 top=-1；top==-1 表示栈空；"
    "top==capacity-1 表示栈满。",
    "顺序栈入栈先检查栈满；未满时先令 top 增加 1，再把新元素写入 data[top]。"
    "入栈成功后，新元素成为栈顶。",
    "顺序栈出栈先检查栈空；非空时保存 data[top]，再令 top 减少 1。读取栈顶只返回"
    "data[top]，不修改 top。",
    "链栈以单链表头部作为栈顶，top 指向栈顶结点。空链栈的 top=nullptr。入栈创建新结点"
    "并链接到原 top，出栈保存 top 数据后移动 top 并释放原结点。",
    "在不触发扩容或内存分配异常的前提下，顺序栈和链栈的入栈、出栈、读取栈顶与判空操作"
    "时间复杂度均为 O(1)。顺序栈容量固定时可能上溢，链栈受可用内存限制。",
    "括号匹配从左到右扫描字符。遇到左括号入栈；遇到右括号时，栈不能为空且栈顶左括号"
    "必须与其类型匹配，然后出栈；扫描结束后栈也必须为空。",
    "表达式处理中可以使用操作数栈保存数值、使用运算符栈保存符号。执行二元运算时先弹出"
    "右操作数，再弹出左操作数，计算后把结果压回操作数栈。",
    "递归调用由运行时调用栈管理。每次调用建立活动记录，保存参数、局部变量和返回地址；"
    "函数返回时对应活动记录出栈。递归必须具有可到达的终止条件。",
    "C++ 顺序栈可以提供 push、pop、topValue 和 empty 函数。push 在满栈时返回失败；pop 和"
    "topValue 在空栈时返回失败。任何实现都不得在检查边界前访问 data[top]。",
)

_SYNTHETIC_SORTING_TEXTS = (
    "排序是把记录按关键字组织成递增或递减序列。若关键字相等的记录排序后相对次序不变，"
    "该排序算法称为稳定排序；否则是不稳定排序。",
    "直接插入排序把序列分成有序区和无序区。第 i 趟保存 a[i]，从有序区末尾向前比较并移动"
    "较大元素，再把保存值放入空位。最好时间 O(n)，平均和最坏时间 O(n^2)，空间 O(1)，稳定。",
    "冒泡排序反复比较相邻元素，逆序时交换。若某一趟没有发生交换即可提前结束。最好时间 O(n)，"
    "平均和最坏时间 O(n^2)，空间 O(1)，稳定。",
    "简单选择排序每趟从未排序区选择最小元素，与未排序区首元素交换。时间始终为 O(n^2)，"
    "空间 O(1)，通常不稳定。",
    "快速排序选择枢轴并进行划分，使枢轴左侧元素不大于它、右侧元素不小于它，再递归处理两侧。"
    "平均时间 O(n log n)，最坏时间 O(n^2)，通常不稳定。递归边界必须缩小区间。",
    "归并排序先递归拆分序列，再合并两个有序子序列。合并时关键字相等应先取左子序列元素以保持"
    "稳定性。时间 O(n log n)，数组实现需要 O(n) 辅助空间，稳定。",
    "堆排序先建立大根堆；升序排序时把堆顶最大元素与当前末尾交换，缩小堆范围并向下调整。"
    "时间 O(n log n)，辅助空间 O(1)，通常不稳定。",
    "希尔排序按逐渐缩小的增量对子序列执行插入排序，最后增量必须为 1。其性能依赖增量序列，"
    "通常不稳定，不能统一写成所有增量下都具有同一个精确时间上界。",
    "对序列 5, 2, 4 执行直接插入排序：插入 2 后得到 2, 5, 4；再插入 4 得到 2, 4, 5。"
    "对相邻逆序元素交换的冒泡排序也能得到 2, 4, 5。",
    "C++ 排序实现应明确半开区间或闭区间。快速排序若使用闭区间 [left,right]，终止条件可写"
    "left>=right；归并时辅助数组写回原数组不可漏掉边界元素；空序列和单元素序列应直接结束。",
)


def _sqlite_path(database_url: str) -> Path:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("The exam audit expects the local SQLite database.")
    return Path(database_url.removeprefix(prefix)).resolve()


def _ready_scope(database_url: str, requested_course_id: str | None) -> tuple[UUID, list[str]]:
    with sqlite3.connect(_sqlite_path(database_url)) as connection:
        if requested_course_id:
            course_row = connection.execute(
                "SELECT id, name FROM courses WHERE id = ?",
                (UUID(requested_course_id).hex,),
            ).fetchone()
        else:
            course_row = connection.execute(
                "SELECT id, name FROM courses ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if course_row is None:
            raise RuntimeError("No course was found for the exam audit.")
        course_id = UUID(str(course_row[0]))
        document_rows = connection.execute(
            "SELECT id FROM documents WHERE course_id = ? AND status = 'completed'",
            (course_id.hex,),
        ).fetchall()
    document_ids = [str(UUID(str(row[0]))) for row in document_rows]
    if not document_ids:
        raise RuntimeError("The selected course has no completed documents.")
    return course_id, document_ids


def _bounded_hits(
    hits: tuple[VectorSearchResult, ...],
    *,
    max_sources: int,
    max_chars: int,
) -> tuple[VectorSearchResult, ...]:
    selected: list[VectorSearchResult] = []
    used_chars = 0
    for hit in hits[:max_sources]:
        remaining = max_chars - used_chars
        if remaining < 400:
            break
        selected_hit = (
            hit
            if len(hit.text) <= remaining
            else replace(hit, text=hit.text[:remaining])
        )
        selected.append(selected_hit)
        used_chars += len(selected_hit.text)
    return tuple(selected)


async def _run(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    plan = build_exam_plan(arguments.request, allow_external=not arguments.course_only)
    hits: tuple[VectorSearchResult, ...]
    if arguments.synthetic:
        course_id = UUID("00000000-0000-0000-0000-000000000001")
        document_ids = ["00000000-0000-0000-0000-000000000002"]
        synthetic_texts = (
            _SYNTHETIC_SORTING_TEXTS
            if arguments.synthetic_topic == "sorting"
            else _SYNTHETIC_STACK_TEXTS
        )
        hits = tuple(
            VectorSearchResult(
                point_id=f"synthetic-stack-{index}",
                score=0.96 - index / 100,
                course_id=str(course_id),
                document_id=document_ids[0],
                chunk_index=index,
                text=text,
                payload={
                    "file_name": "synthetic.md",
                    "content_role": "exposition",
                },
            )
            for index, text in enumerate(synthetic_texts, start=1)
        )
        retrieved_count = len(hits)
    else:
        course_id, document_ids = _ready_scope(settings.database_url, arguments.course_id)
        pipeline = DocumentIndexingPipeline(settings)
        try:
            retrieval = pipeline.exam_search(
                course_id=course_id,
                query=plan.retrieval_query,
                candidate_k=settings.rag_exam_candidate_k,
                top_k=settings.rag_exam_top_k,
                document_ids=document_ids,
            )
        finally:
            pipeline.close()
        hits = _bounded_hits(
            retrieval.hits,
            max_sources=settings.rag_exam_max_sources,
            max_chars=settings.rag_exam_context_max_chars,
        )
        retrieved_count = len(retrieval.hits)
    external_result = None
    external_evidence: tuple[ExternalSearchEvidence, ...] = ()
    if plan.allow_external:
        external_result = await DeepSeekWebSearchAdapter(settings).search(
            query=(
                f"{arguments.request} 高质量课程练习题 官方或大学教学资料 "
                f"{plan.programming_language}"
            ),
            model=settings.llm_model,
        )
        if external_result.status is ExternalSearchStatus.SUCCEEDED:
            external_evidence = external_result.results
    result = await GroundedExamGenerator(OpenAICompatibleChatClient(settings)).generate(
        request=arguments.request,
        plan=plan,
        course_hits=hits,
        external_evidence=external_evidence,
        model=settings.llm_model,
    )
    print(
        json.dumps(
            {
                "request": arguments.request,
                "course_id": str(course_id),
                "document_count": len(document_ids),
                "synthetic": arguments.synthetic,
                "retrieved_count": retrieved_count,
                "used_course_context_count": len(hits),
                "external_status": (
                    external_result.status.value if external_result is not None else "not_requested"
                ),
                "external_result_count": (
                    len(external_result.results) if external_result is not None else 0
                ),
                "plan": plan.model_dump(mode="json"),
                "quality": result.quality.model_dump(mode="json"),
                "used_course_source_ids": result.answer.used_source_ids,
                "used_external_source_ids": result.answer.used_external_source_ids,
                "status": result.answer.status.value,
                "model": result.answer.model,
                "usage": (
                    asdict(result.answer.usage)
                    if result.answer.usage is not None
                    else None
                ),
                "answer": result.answer.answer,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--request",
        default="请根据当前课程生成一份默认试卷，包含答案和解析。",
    )
    parser.add_argument("--course-id")
    parser.add_argument("--course-only", action="store_true")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument(
        "--synthetic-topic",
        choices=("stack", "sorting"),
        default="stack",
    )
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
