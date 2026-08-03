from __future__ import annotations

from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, IndexStorageError
from app.db.session import get_session
from app.indexing import DocumentIndexingManager, get_indexing_manager
from app.knowledge.models import VectorSearchResult
from app.models import DocumentStatus
from app.schemas.api import APIResponse
from app.schemas.retrieval import (
    RetrievalHitRead,
    RetrievalSearchRead,
    RetrievalSearchRequest,
)
from app.services import CourseService, DocumentService

router = APIRouter(tags=["retrieval"])

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
IndexingDependency = Annotated[
    DocumentIndexingManager,
    Depends(get_indexing_manager),
]


@router.post(
    "/courses/{course_id}/retrieval/search",
    response_model=APIResponse[RetrievalSearchRead],
)
async def search_course_materials(
    course_id: UUID,
    payload: RetrievalSearchRequest,
    session: SessionDependency,
    indexing: IndexingDependency,
) -> APIResponse[RetrievalSearchRead]:
    started_at = perf_counter()
    await CourseService(session).get(course_id)
    document_service = DocumentService(session)

    if payload.document_ids is None:
        candidate_documents = await document_service.list_for_course(course_id)
    else:
        candidate_documents = await document_service.get_many_for_course(
            course_id=course_id,
            document_ids=payload.document_ids,
        )
        unavailable = [
            document.original_name
            for document in candidate_documents
            if document.status is not DocumentStatus.COMPLETED
        ]
        if unavailable:
            raise ConflictError(
                "Only completed documents can be searched. Unavailable: "
                + ", ".join(unavailable)
            )

    ready_document_ids = [
        str(document.id)
        for document in candidate_documents
        if document.status is DocumentStatus.COMPLETED
    ]
    try:
        retrieval = await indexing.search(
            course_id=course_id,
            query=payload.query,
            top_k=payload.top_k,
            document_ids=ready_document_ids,
        )
    except (FileNotFoundError, RuntimeError, OSError) as error:
        raise IndexStorageError(
            "检索暂时不可用，请检查本地 Embedding 模型与 Qdrant 存储后重试。"
        ) from error

    results = [
        _hit_read(rank=rank, result=result)
        for rank, result in enumerate(retrieval.hits, start=1)
    ]
    return APIResponse(
        data=RetrievalSearchRead(
            course_id=course_id,
            query=retrieval.query,
            requested_top_k=payload.top_k,
            returned_count=len(results),
            scope_document_count=len(ready_document_ids),
            elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
            embedding_device=retrieval.embedding_device,
            fallback_reason=retrieval.fallback_reason,
            results=results,
        )
    )


def _hit_read(*, rank: int, result: VectorSearchResult) -> RetrievalHitRead:
    payload = result.payload
    return RetrievalHitRead(
        rank=rank,
        score=result.score,
        point_id=result.point_id,
        document_id=UUID(result.document_id),
        chunk_index=result.chunk_index,
        text=result.text,
        file_name=str(payload.get("file_name", "")),
        file_type=str(payload.get("file_type", "")),
        section_path=[str(value) for value in payload.get("section_path", [])],
        page_numbers=[int(value) for value in payload.get("page_numbers", [])],
        slide_numbers=[int(value) for value in payload.get("slide_numbers", [])],
        line_start=_optional_int(payload.get("line_start")),
        line_end=_optional_int(payload.get("line_end")),
    )


def _optional_int(value: object) -> int | None:
    if isinstance(value, (int, str)):
        return int(value)
    return None
