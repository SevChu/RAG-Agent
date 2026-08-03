from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.session import create_database_engine
from app.indexing import get_indexing_manager
from app.knowledge import VectorSearchResult
from app.main import app
from app.models import Document, DocumentStatus
from app.retrieval import DenseRetrievalResult


async def _create_course(client: AsyncClient, name: str = "数据结构") -> str:
    response = await client.post("/api/courses", json={"name": name})
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


async def _upload_markdown(client: AsyncClient, course_id: str) -> str:
    response = await client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("数据结构讲义.md", "# 栈\n\n后进先出".encode(), "text/markdown")},
    )
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


async def _mark_completed(database_url: str, document_id: str) -> None:
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        document = await session.get(Document, UUID(document_id))
        assert document is not None
        document.status = DocumentStatus.COMPLETED
        await session.commit()
    await engine.dispose()


class FakeRetrievalManager:
    def __init__(self, *, document_id: str) -> None:
        self.document_id = document_id
        self.calls: list[dict[str, object]] = []

    async def search(
        self,
        *,
        course_id: UUID,
        query: str,
        top_k: int,
        document_ids: list[str],
    ) -> DenseRetrievalResult:
        self.calls.append(
            {
                "course_id": course_id,
                "query": query,
                "top_k": top_k,
                "document_ids": document_ids,
            }
        )
        return DenseRetrievalResult(
            query=query.strip(),
            embedding_device="cpu",
            fallback_reason=None,
            hits=(
                VectorSearchResult(
                    point_id="point-1",
                    score=0.875,
                    course_id=str(course_id),
                    document_id=self.document_id,
                    chunk_index=3,
                    text="栈是一种后进先出的线性表。",
                    payload={
                        "file_name": "数据结构讲义.md",
                        "file_type": "md",
                        "section_path": ["栈", "基本概念"],
                        "page_numbers": [],
                        "slide_numbers": [],
                        "line_start": 12,
                        "line_end": 18,
                    },
                ),
            ),
        )


async def test_retrieval_api_returns_traceable_dense_hits(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id = await _create_course(api_client)
    document_id = await _upload_markdown(api_client, course_id)
    database_url = api_settings.database_url
    await _mark_completed(database_url, document_id)
    manager = FakeRetrievalManager(document_id=document_id)
    app.dependency_overrides[get_indexing_manager] = lambda: manager

    response = await api_client.post(
        f"/api/courses/{course_id}/retrieval/search",
        json={"query": "  什么是栈？  ", "top_k": 5},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["retrieval_mode"] == "dense"
    assert data["query"] == "什么是栈？"
    assert data["requested_top_k"] == 5
    assert data["returned_count"] == 1
    assert data["scope_document_count"] == 1
    assert data["embedding_device"] == "cpu"
    assert data["results"][0] == {
        "rank": 1,
        "score": 0.875,
        "point_id": "point-1",
        "document_id": document_id,
        "chunk_index": 3,
        "text": "栈是一种后进先出的线性表。",
        "file_name": "数据结构讲义.md",
        "file_type": "md",
        "section_path": ["栈", "基本概念"],
        "page_numbers": [],
        "slide_numbers": [],
        "line_start": 12,
        "line_end": 18,
    }
    assert manager.calls[0]["document_ids"] == [document_id]


async def test_retrieval_api_rejects_unready_explicit_document(
    api_client: AsyncClient,
) -> None:
    course_id = await _create_course(api_client, "未完成资料测试")
    document_id = await _upload_markdown(api_client, course_id)

    response = await api_client.post(
        f"/api/courses/{course_id}/retrieval/search",
        json={"query": "什么是栈？", "document_ids": [document_id]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_retrieval_api_validates_query_and_top_k(api_client: AsyncClient) -> None:
    course_id = await _create_course(api_client, "检索参数测试")

    blank = await api_client.post(
        f"/api/courses/{course_id}/retrieval/search",
        json={"query": "   "},
    )
    too_many = await api_client.post(
        f"/api/courses/{course_id}/retrieval/search",
        json={"query": "队列", "top_k": 21},
    )

    assert blank.status_code == 422
    assert too_many.status_code == 422
    assert blank.json()["error"]["code"] == "VALIDATION_ERROR"
    assert too_many.json()["error"]["code"] == "VALIDATION_ERROR"
