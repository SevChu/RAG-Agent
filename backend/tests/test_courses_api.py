from uuid import uuid4

from httpx import AsyncClient


async def test_course_crud_and_error_envelope(api_client: AsyncClient) -> None:
    create_response = await api_client.post(
        "/api/courses",
        json={
            "name": "  数据结构  ",
            "description": "  课程简介  ",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["error"] is None
    assert created["data"]["name"] == "数据结构"
    assert created["data"]["description"] == "课程简介"
    course_id = created["data"]["id"]

    duplicate_response = await api_client.post(
        "/api/courses",
        json={"name": "数据结构"},
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "CONFLICT"

    list_response = await api_client.get("/api/courses")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["data"]] == [course_id]

    detail_response = await api_client.get(f"/api/courses/{course_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["name"] == "数据结构"

    delete_response = await api_client.delete(f"/api/courses/{course_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {
        "id": course_id,
        "deleted": True,
    }

    missing_response = await api_client.get(f"/api/courses/{course_id}")
    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "data": None,
        "error": {
            "code": "NOT_FOUND",
            "message": "Course not found.",
        },
    }


async def test_course_request_validation_uses_error_envelope(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post("/api/courses", json={"name": ""})

    assert response.status_code == 422
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    whitespace_response = await api_client.post(
        "/api/courses",
        json={"name": "   "},
    )
    assert whitespace_response.status_code == 400
    assert whitespace_response.json()["error"]["code"] == "INVALID_INPUT"


async def test_invalid_course_id_uses_error_envelope(api_client: AsyncClient) -> None:
    response = await api_client.get(f"/api/courses/{uuid4().hex[:8]}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_local_frontend_origin_is_allowed(api_client: AsyncClient) -> None:
    response = await api_client.options(
        "/api/courses",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
