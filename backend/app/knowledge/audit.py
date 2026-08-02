from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import create_database_engine
from app.knowledge.models import VectorPointSnapshot
from app.knowledge.vector_store import QdrantChunkStore
from app.models import Course, Document, DocumentStatus

_REQUIRED_PAYLOAD_FIELDS = frozenset(
    {
        "course_id",
        "document_id",
        "chunk_index",
        "text",
        "estimated_token_count",
        "overlap_token_count",
        "file_name",
        "file_type",
        "parser_name",
        "section_path",
        "source_block_start",
        "source_block_end",
        "source_block_indices",
        "context_block_indices",
        "block_kinds",
        "line_start",
        "line_end",
        "page_numbers",
        "slide_numbers",
        "extraction_methods",
        "minimum_ocr_confidence",
    }
)


@dataclass(frozen=True, slots=True)
class AuditIssue:
    code: str
    message: str
    course_id: str | None = None
    document_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkSample:
    chunk_index: int
    section_path: tuple[str, ...]
    page_numbers: tuple[int, ...]
    slide_numbers: tuple[int, ...]
    block_kinds: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class DocumentAuditSummary:
    course_id: str
    course_name: str
    document_id: str
    file_name: str
    file_type: str
    status: str
    source_exists: bool
    point_count: int
    chunk_index_start: int | None
    chunk_index_end: int | None
    page_numbers: tuple[int, ...]
    slide_numbers: tuple[int, ...]
    section_paths: tuple[tuple[str, ...], ...]
    samples: tuple[ChunkSample, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeBaseAuditReport:
    course_count: int
    document_count: int
    upload_file_count: int
    vector_point_count: int
    documents: tuple[DocumentAuditSummary, ...]
    errors: tuple[AuditIssue, ...]
    warnings: tuple[AuditIssue, ...]

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


class KnowledgeBaseAuditor:
    """Check SQLite, upload files and Qdrant payloads as one logical store."""

    def __init__(self, upload_dir: Path, *, sample_chunks: int = 3) -> None:
        if sample_chunks < 1:
            raise ValueError("sample_chunks must be positive.")
        self.upload_dir = upload_dir.resolve()
        self.sample_chunks = sample_chunks

    def audit(
        self,
        *,
        courses: list[Course],
        documents: list[Document],
        points: tuple[VectorPointSnapshot, ...],
    ) -> KnowledgeBaseAuditReport:
        errors: list[AuditIssue] = []
        warnings: list[AuditIssue] = []
        courses_by_id = {str(course.id): course for course in courses}
        documents_by_id = {str(document.id): document for document in documents}
        points_by_document: dict[str, list[VectorPointSnapshot]] = defaultdict(list)

        for point in points:
            payload = point.payload
            missing = sorted(_REQUIRED_PAYLOAD_FIELDS - payload.keys())
            document_id = _optional_text(payload.get("document_id"))
            course_id = _optional_text(payload.get("course_id"))
            if missing:
                errors.append(
                    AuditIssue(
                        code="INCOMPLETE_VECTOR_METADATA",
                        message=f"向量 {point.point_id} 缺少来源字段：{', '.join(missing)}。",
                        course_id=course_id,
                        document_id=document_id,
                    )
                )
            if document_id is None or document_id not in documents_by_id:
                errors.append(
                    AuditIssue(
                        code="ORPHAN_VECTOR",
                        message=f"向量 {point.point_id} 找不到对应的 SQLite 资料记录。",
                        course_id=course_id,
                        document_id=document_id,
                    )
                )
                continue
            points_by_document[document_id].append(point)

        expected_files: set[Path] = set()
        summaries: list[DocumentAuditSummary] = []
        for document in sorted(
            documents,
            key=lambda item: (str(item.course_id), item.original_name),
        ):
            document_id = str(document.id)
            course_id = str(document.course_id)
            course = courses_by_id.get(course_id)
            source_path = (self.upload_dir / course_id / document.stored_name).resolve()
            expected_files.add(source_path)
            source_exists = source_path.is_file()
            document_points = points_by_document.get(document_id, [])
            self._check_document(
                document,
                course_exists=course is not None,
                source_path=source_path,
                source_exists=source_exists,
                points=document_points,
                errors=errors,
                warnings=warnings,
            )
            summaries.append(
                self._summary(
                    document,
                    course_name=course.name if course is not None else "<课程记录缺失>",
                    source_exists=source_exists,
                    points=document_points,
                )
            )

        upload_files = self._upload_files()
        for orphan in sorted(upload_files - expected_files):
            errors.append(
                AuditIssue(
                    code="ORPHAN_UPLOAD_FILE",
                    message=f"上传目录中存在没有 SQLite 记录的文件：{orphan.name}。",
                )
            )

        if not documents:
            warnings.append(
                AuditIssue(
                    code="EMPTY_KNOWLEDGE_BASE",
                    message="当前没有资料记录；存储一致，但不能据此验收完整入库流程。",
                )
            )

        return KnowledgeBaseAuditReport(
            course_count=len(courses),
            document_count=len(documents),
            upload_file_count=len(upload_files),
            vector_point_count=len(points),
            documents=tuple(summaries),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def _check_document(
        self,
        document: Document,
        *,
        course_exists: bool,
        source_path: Path,
        source_exists: bool,
        points: list[VectorPointSnapshot],
        errors: list[AuditIssue],
        warnings: list[AuditIssue],
    ) -> None:
        course_id = str(document.course_id)
        document_id = str(document.id)
        if not course_exists:
            errors.append(
                AuditIssue(
                    code="MISSING_COURSE",
                    message="资料引用的课程记录不存在。",
                    course_id=course_id,
                    document_id=document_id,
                )
            )
        if not source_exists:
            errors.append(
                AuditIssue(
                    code="MISSING_SOURCE_FILE",
                    message=f"资料原文件缺失：{document.original_name}。",
                    course_id=course_id,
                    document_id=document_id,
                )
            )
        elif source_path.stat().st_size != document.file_size:
            errors.append(
                AuditIssue(
                    code="SOURCE_SIZE_MISMATCH",
                    message=f"资料原文件大小与 SQLite 记录不一致：{document.original_name}。",
                    course_id=course_id,
                    document_id=document_id,
                )
            )

        if document.status is DocumentStatus.COMPLETED and not points:
            errors.append(
                AuditIssue(
                    code="COMPLETED_WITHOUT_VECTORS",
                    message=f"已完成资料没有任何向量：{document.original_name}。",
                    course_id=course_id,
                    document_id=document_id,
                )
            )
        if document.status is not DocumentStatus.COMPLETED and points:
            errors.append(
                AuditIssue(
                    code="UNFINISHED_WITH_VECTORS",
                    message=f"未完成资料仍残留 {len(points)} 个向量：{document.original_name}。",
                    course_id=course_id,
                    document_id=document_id,
                )
            )
        if document.status is DocumentStatus.FAILED and not document.error_message:
            errors.append(
                AuditIssue(
                    code="FAILED_WITHOUT_REASON",
                    message=f"失败资料没有可读原因：{document.original_name}。",
                    course_id=course_id,
                    document_id=document_id,
                )
            )
        if document.status is DocumentStatus.COMPLETED and document.error_message:
            warnings.append(
                AuditIssue(
                    code="STALE_ERROR_MESSAGE",
                    message=f"已完成资料仍保留旧错误文本：{document.original_name}。",
                    course_id=course_id,
                    document_id=document_id,
                )
            )

        indexes: list[int] = []
        for point in points:
            payload = point.payload
            if _optional_text(payload.get("course_id")) != course_id:
                errors.append(
                    AuditIssue(
                        code="CROSS_COURSE_VECTOR",
                        message=f"资料 {document.original_name} 的向量 course_id 不一致。",
                        course_id=course_id,
                        document_id=document_id,
                    )
                )
            if payload.get("file_name") != document.original_name or payload.get(
                "file_type"
            ) != document.file_type:
                errors.append(
                    AuditIssue(
                        code="VECTOR_DOCUMENT_MISMATCH",
                        message=f"资料 {document.original_name} 的向量文件元数据不一致。",
                        course_id=course_id,
                        document_id=document_id,
                    )
                )
            chunk_index = payload.get("chunk_index")
            if isinstance(chunk_index, int) and chunk_index >= 0:
                indexes.append(chunk_index)
            else:
                errors.append(
                    AuditIssue(
                        code="INVALID_CHUNK_INDEX",
                        message=f"资料 {document.original_name} 存在无效 Chunk 序号。",
                        course_id=course_id,
                        document_id=document_id,
                    )
                )
            if not _optional_text(payload.get("text")):
                errors.append(
                    AuditIssue(
                        code="EMPTY_VECTOR_TEXT",
                        message=f"资料 {document.original_name} 存在空白向量正文。",
                        course_id=course_id,
                        document_id=document_id,
                    )
                )
            if document.file_type == "pdf" and not payload.get("page_numbers"):
                errors.append(
                    AuditIssue(
                        code="PDF_PAGE_MISSING",
                        message=f"PDF 资料 {document.original_name} 的 Chunk 缺少页码。",
                        course_id=course_id,
                        document_id=document_id,
                    )
                )
            if document.file_type == "pptx" and not payload.get("slide_numbers"):
                errors.append(
                    AuditIssue(
                        code="PPTX_SLIDE_MISSING",
                        message=f"PPTX 资料 {document.original_name} 的 Chunk 缺少幻灯片编号。",
                        course_id=course_id,
                        document_id=document_id,
                    )
                )

        if indexes and sorted(indexes) != list(range(len(indexes))):
            errors.append(
                AuditIssue(
                    code="NON_CONTIGUOUS_CHUNKS",
                    message=f"资料 {document.original_name} 的 Chunk 序号不连续或重复。",
                    course_id=course_id,
                    document_id=document_id,
                )
            )

    def _summary(
        self,
        document: Document,
        *,
        course_name: str,
        source_exists: bool,
        points: list[VectorPointSnapshot],
    ) -> DocumentAuditSummary:
        ordered = sorted(
            points,
            key=_point_chunk_index,
        )
        indexes = [
            int(item.payload["chunk_index"])
            for item in ordered
            if isinstance(item.payload.get("chunk_index"), int)
        ]
        pages = _merged_ints(item.payload.get("page_numbers") for item in ordered)
        slides = _merged_ints(item.payload.get("slide_numbers") for item in ordered)
        sections = tuple(
            dict.fromkeys(
                tuple(str(part) for part in item.payload.get("section_path", []))
                for item in ordered
                if item.payload.get("section_path")
            )
        )
        samples = tuple(
            self._sample(item.payload)
            for item in _spread_samples(ordered, self.sample_chunks)
        )
        return DocumentAuditSummary(
            course_id=str(document.course_id),
            course_name=course_name,
            document_id=str(document.id),
            file_name=document.original_name,
            file_type=document.file_type,
            status=document.status.value,
            source_exists=source_exists,
            point_count=len(points),
            chunk_index_start=min(indexes, default=None),
            chunk_index_end=max(indexes, default=None),
            page_numbers=pages,
            slide_numbers=slides,
            section_paths=sections,
            samples=samples,
        )

    @staticmethod
    def _sample(payload: dict[str, Any]) -> ChunkSample:
        text = " ".join(str(payload.get("text", "")).split())
        return ChunkSample(
            chunk_index=int(payload.get("chunk_index", -1)),
            section_path=tuple(str(value) for value in payload.get("section_path", [])),
            page_numbers=tuple(int(value) for value in payload.get("page_numbers", [])),
            slide_numbers=tuple(int(value) for value in payload.get("slide_numbers", [])),
            block_kinds=tuple(str(value) for value in payload.get("block_kinds", [])),
            text=text,
        )

    def _upload_files(self) -> set[Path]:
        if not self.upload_dir.is_dir():
            return set()
        return {
            path.resolve()
            for path in self.upload_dir.rglob("*")
            if path.is_file()
            and not any(part in {".staging", ".trash"} for part in path.parts)
        }


def render_markdown(report: KnowledgeBaseAuditReport) -> str:
    result = "通过" if report.passed else "未通过"
    lines = [
        "# 第二周知识库一致性与结构抽查报告",
        "",
        f"> 自动检查结论：**{result}**",
        "",
        "## 总览",
        "",
        "| 课程 | SQLite 资料 | 上传文件 | Qdrant 向量 | 错误 | 提醒 |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {report.course_count} | {report.document_count} | "
            f"{report.upload_file_count} | {report.vector_point_count} | "
            f"{len(report.errors)} | {len(report.warnings)} |"
        ),
        "",
        "## 自动一致性问题",
        "",
    ]
    if report.errors:
        lines.extend(f"- `{issue.code}`：{issue.message}" for issue in report.errors)
    else:
        lines.append("- 未发现 SQLite、上传目录和 Qdrant 之间的不一致。")
    if report.warnings:
        lines.extend(("", "## 提醒", ""))
        lines.extend(f"- `{issue.code}`：{issue.message}" for issue in report.warnings)

    lines.extend(("", "## 资料结构与 Chunk 肉眼抽查", ""))
    if not report.documents:
        lines.append("当前没有资料可供抽查。")
    for document in report.documents:
        lines.extend(
            (
                f"### {document.file_name}",
                "",
                (
                    f"- 课程：{document.course_name}；类型：`{document.file_type}`；"
                    f"状态：`{document.status}`；Chunk：{document.point_count}"
                ),
                f"- 页码范围：{_compact_numbers(document.page_numbers)}",
                f"- 幻灯片范围：{_compact_numbers(document.slide_numbers)}",
                "- 主要章节："
                + (
                    "；".join(" / ".join(path) for path in document.section_paths[:12])
                    if document.section_paths
                    else "未识别章节层级"
                ),
                "",
            )
        )
        for sample in document.samples:
            location = []
            if sample.page_numbers:
                location.append(f"页 {_compact_numbers(sample.page_numbers)}")
            if sample.slide_numbers:
                location.append(f"幻灯片 {_compact_numbers(sample.slide_numbers)}")
            if sample.section_path:
                location.append(" / ".join(sample.section_path))
            lines.extend(
                (
                    f"#### Chunk {sample.chunk_index}"
                    + (f"（{'；'.join(location)}）" if location else ""),
                    "",
                    f"> {sample.text}",
                    "",
                )
            )
    lines.extend(
        (
            "## 你的最终肉眼标准",
            "",
            "1. 章节名称、PDF 页码或 PPTX 幻灯片编号能对应原资料；",
            "2. 每个示例 Chunk 单独阅读时语义基本完整，没有明显跨章节拼接；",
            "3. 列表、表格、代码与公式附近的相关说明没有被无理由拆散；",
            "4. 文件名、课程归属和资料类型正确，没有混入其他课程内容。",
            "",
        )
    )
    return "\n".join(lines)


async def audit_configured_knowledge_base(settings: Settings) -> KnowledgeBaseAuditReport:
    engine = create_database_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    store: QdrantChunkStore | None = None
    try:
        async with session_factory() as session:
            courses = list((await session.execute(select(Course))).scalars())
            documents = list((await session.execute(select(Document))).scalars())
        points: tuple[VectorPointSnapshot, ...] = ()
        if settings.qdrant_path.is_dir():
            store = QdrantChunkStore(
                settings.qdrant_path,
                collection_name=settings.qdrant_collection_name,
            )
            points = await asyncio.to_thread(store.list_points)
        return KnowledgeBaseAuditor(settings.upload_dir).audit(
            courses=courses,
            documents=documents,
            points=points,
        )
    finally:
        await engine.dispose()
        if store is not None:
            await asyncio.to_thread(store.close)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit SQLite, uploaded files and Qdrant, then build a structure report."
    )
    parser.add_argument("--output", type=Path, help="Optional Markdown report path.")
    parser.add_argument("--json-output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()
    report = asyncio.run(audit_configured_knowledge_base(get_settings()))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_markdown(report), encoding="utf-8")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    output = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(f"{output}\n".encode())
    raise SystemExit(0 if report.passed else 1)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _point_chunk_index(point: VectorPointSnapshot) -> int:
    value = point.payload.get("chunk_index")
    return value if isinstance(value, int) else -1


def _spread_samples(
    points: list[VectorPointSnapshot],
    limit: int,
) -> tuple[VectorPointSnapshot, ...]:
    if len(points) <= limit:
        return tuple(points)
    if limit == 1:
        return (points[0],)
    positions = {
        round(index * (len(points) - 1) / (limit - 1))
        for index in range(limit)
    }
    return tuple(points[position] for position in sorted(positions))


def _merged_ints(values: Any) -> tuple[int, ...]:
    merged: set[int] = set()
    for group in values:
        if isinstance(group, list):
            merged.update(int(value) for value in group)
    return tuple(sorted(merged))


def _compact_numbers(values: tuple[int, ...]) -> str:
    if not values:
        return "—"
    if len(values) <= 8:
        return "、".join(str(value) for value in values)
    return f"{values[0]}～{values[-1]}（共 {len(values)} 个）"


if __name__ == "__main__":
    main()
