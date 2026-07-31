from __future__ import annotations

from io import BytesIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from httpx import AsyncClient

from app.core.config import Settings


async def create_course(client: AsyncClient, name: str) -> str:
    response = await client.post("/api/courses", json={"name": name})
    assert response.status_code == 201
    return str(response.json()["data"]["id"])


def office_file(required_member: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(required_member, "<document />")
    return buffer.getvalue()


VALID_UPLOADS = [
    ("讲义.pdf", b"%PDF-1.4\nsynthetic\n%%EOF", "application/pdf"),
    (
        "课件.pptx",
        office_file("ppt/presentation.xml"),
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    (
        "实验说明.docx",
        office_file("word/document.xml"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ("学习笔记.md", "# 标题\n\nUTF-8 内容".encode(), "text/markdown"),
    ("复习提纲.txt", "中英文 UTF-8 text".encode(), "text/plain"),
]


@pytest.mark.parametrize(("filename", "content", "content_type"), VALID_UPLOADS)
async def test_upload_accepts_all_supported_file_types(
    api_client: AsyncClient,
    api_settings: Settings,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    course_id = await create_course(api_client, f"课程-{filename}")

    response = await api_client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 201
    document = response.json()["data"]
    assert document["original_name"] == filename
    assert document["status"] == "pending"
    assert document["file_size"] == len(content)
    stored_files = list((api_settings.upload_dir / course_id).iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].name.startswith(document["id"])


async def test_duplicate_is_rejected_per_course_but_allowed_across_courses(
    api_client: AsyncClient,
) -> None:
    first_course = await create_course(api_client, "操作系统")
    second_course = await create_course(api_client, "计算机网络")
    content = "相同内容".encode()

    first_response = await api_client.post(
        f"/api/courses/{first_course}/documents",
        files={"file": ("原始.txt", content, "text/plain")},
    )
    assert first_response.status_code == 201

    duplicate_response = await api_client.post(
        f"/api/courses/{first_course}/documents",
        files={"file": ("改名副本.txt", content, "text/plain")},
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "CONFLICT"

    cross_course_response = await api_client.post(
        f"/api/courses/{second_course}/documents",
        files={"file": ("同一资料.txt", content, "text/plain")},
    )
    assert cross_course_response.status_code == 201


@pytest.mark.parametrize(
    ("filename", "content", "expected_status", "expected_code"),
    [
        ("空文件.txt", b"", 400, "INVALID_INPUT"),
        ("资料.csv", b"a,b\n1,2", 415, "UNSUPPORTED_FILE_TYPE"),
        ("伪装.pdf", b"plain text", 415, "UNSUPPORTED_FILE_TYPE"),
        ("错误编码.md", b"\xff\xfe\x00\x00", 415, "UNSUPPORTED_FILE_TYPE"),
    ],
)
async def test_invalid_uploads_are_rejected_and_not_persisted(
    api_client: AsyncClient,
    api_settings: Settings,
    filename: str,
    content: bytes,
    expected_status: int,
    expected_code: str,
) -> None:
    course_id = await create_course(api_client, f"异常-{filename}")

    response = await api_client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": (filename, content, "application/octet-stream")},
    )

    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == expected_code
    course_dir = api_settings.upload_dir / course_id
    assert not course_dir.exists() or not any(course_dir.iterdir())


async def test_upload_enforces_size_limit_and_cleans_staging(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id = await create_course(api_client, "大文件测试")
    content = b"x" * (1024 * 1024 + 1)

    response = await api_client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("large.txt", content, "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    staging_dir = api_settings.upload_dir / ".staging"
    assert staging_dir.is_dir()
    assert not any(staging_dir.iterdir())


async def test_document_queries_and_delete_remove_database_and_file(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id = await create_course(api_client, "数据库系统")
    upload_response = await api_client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("../../安全名称.txt", b"content", "text/plain")},
    )
    document = upload_response.json()["data"]
    document_id = document["id"]
    assert document["original_name"] == "安全名称.txt"

    list_response = await api_client.get(f"/api/courses/{course_id}/documents")
    assert [item["id"] for item in list_response.json()["data"]] == [document_id]

    status_response = await api_client.get(f"/api/documents/{document_id}/status")
    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "pending"

    stored_path = next((api_settings.upload_dir / course_id).iterdir())
    assert stored_path.is_file()

    delete_response = await api_client.delete(f"/api/documents/{document_id}")
    assert delete_response.status_code == 200
    assert not stored_path.exists()

    missing_response = await api_client.get(f"/api/documents/{document_id}")
    assert missing_response.status_code == 404


async def test_bulk_delete_removes_only_selected_documents(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id = await create_course(api_client, "批量删除")
    document_ids: list[str] = []
    for index in range(3):
        response = await api_client.post(
            f"/api/courses/{course_id}/documents",
            files={
                "file": (
                    f"资料-{index}.txt",
                    f"content-{index}".encode(),
                    "text/plain",
                )
            },
        )
        document_ids.append(response.json()["data"]["id"])

    delete_response = await api_client.post(
        f"/api/courses/{course_id}/documents/bulk-delete",
        json={"document_ids": document_ids[:2]},
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {
        "deleted_ids": document_ids[:2],
        "deleted_count": 2,
    }
    remaining_response = await api_client.get(
        f"/api/courses/{course_id}/documents"
    )
    assert [item["id"] for item in remaining_response.json()["data"]] == [
        document_ids[2]
    ]
    stored_files = list((api_settings.upload_dir / course_id).iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].name.startswith(document_ids[2])


async def test_bulk_delete_rejects_invalid_selection_without_partial_deletion(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id = await create_course(api_client, "批量删除原子性")
    upload_response = await api_client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("保留.txt", b"keep", "text/plain")},
    )
    document_id = upload_response.json()["data"]["id"]
    stored_path = next((api_settings.upload_dir / course_id).iterdir())

    delete_response = await api_client.post(
        f"/api/courses/{course_id}/documents/bulk-delete",
        json={"document_ids": [document_id, str(uuid4())]},
    )

    assert delete_response.status_code == 404
    assert (await api_client.get(f"/api/documents/{document_id}")).status_code == 200
    assert stored_path.is_file()


async def test_deleting_course_removes_document_records_and_course_directory(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id = await create_course(api_client, "课程级联测试")
    response = await api_client.post(
        f"/api/courses/{course_id}/documents",
        files={"file": ("notes.md", b"# notes", "text/markdown")},
    )
    document_id = response.json()["data"]["id"]
    course_dir = api_settings.upload_dir / course_id
    assert course_dir.is_dir()

    delete_response = await api_client.delete(f"/api/courses/{course_id}")

    assert delete_response.status_code == 200
    assert not course_dir.exists()
    assert (await api_client.get(f"/api/documents/{document_id}")).status_code == 404
