from httpx import AsyncClient


async def test_health_check(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "development",
    }
