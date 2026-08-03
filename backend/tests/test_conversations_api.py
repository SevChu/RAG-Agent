from __future__ import annotations

from httpx import AsyncClient


async def _create_course(client: AsyncClient, name: str = "数据结构") -> str:
    response = await client.post("/api/courses", json={"name": name})
    return str(response.json()["data"]["id"])


async def test_course_conversation_crud_and_global_history(
    api_client: AsyncClient,
) -> None:
    course_id = await _create_course(api_client)

    create_response = await api_client.post(
        f"/api/courses/{course_id}/conversations",
        json={},
    )
    assert create_response.status_code == 201
    conversation = create_response.json()["data"]
    assert conversation["course_id"] == course_id
    assert conversation["course_name"] == "数据结构"
    assert conversation["title"] == "新课程对话"

    list_response = await api_client.get(f"/api/courses/{course_id}/conversations")
    assert [item["id"] for item in list_response.json()["data"]] == [conversation["id"]]

    global_response = await api_client.get("/api/conversations")
    assert [item["id"] for item in global_response.json()["data"]] == [conversation["id"]]

    detail_response = await api_client.get(
        f"/api/courses/{course_id}/conversations/{conversation['id']}"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["messages"] == []

    delete_response = await api_client.delete(
        f"/api/courses/{course_id}/conversations/{conversation['id']}"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["deleted"] is True
    assert (await api_client.get("/api/conversations")).json()["data"] == []


async def test_course_conversation_cannot_be_read_through_another_course(
    api_client: AsyncClient,
) -> None:
    first_course_id = await _create_course(api_client, "数据结构")
    second_course_id = await _create_course(api_client, "操作系统")
    conversation = (
        await api_client.post(
            f"/api/courses/{first_course_id}/conversations",
            json={},
        )
    ).json()["data"]

    response = await api_client.get(
        f"/api/courses/{second_course_id}/conversations/{conversation['id']}"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
