from __future__ import annotations

from httpx import AsyncClient

from app.generation import ChatCompletion, TokenUsage, get_chat_completion_gateway
from app.main import app


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


class QuickGateway:
    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        raise AssertionError("quick chat must not request JSON completion")

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> ChatCompletion:
        assert "不检索课程资料" in system_prompt
        assert "当前用户消息：你好" in user_prompt
        return ChatCompletion(
            content="你好，我可以回答临时问题。",
            model=model,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        )


async def test_quick_conversation_stream_and_history_are_isolated(
    api_client: AsyncClient,
) -> None:
    gateway = QuickGateway()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    conversation = (
        await api_client.post("/api/quick-conversations", json={})
    ).json()["data"]

    response = await api_client.post(
        f"/api/quick-conversations/{conversation['id']}/messages/stream",
        json={"message": "你好", "model": "deepseek-v4-pro"},
    )

    assert response.status_code == 200
    assert "event: start" in response.text
    assert "event: delta" in response.text
    assert "event: complete" in response.text
    detail = (
        await api_client.get(f"/api/quick-conversations/{conversation['id']}")
    ).json()["data"]
    assert detail["title"] == "你好"
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["citations"] == []
    assert detail["messages"][1]["retrieval"] is None
    assert detail["messages"][1]["model"] == "deepseek-v4-pro"
    assert (await api_client.get("/api/conversations")).json()["data"] == []
    quick_history = (await api_client.get("/api/quick-conversations")).json()["data"]
    assert [item["id"] for item in quick_history] == [conversation["id"]]
