from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import create_database_engine
from app.models import TokenUsageEvent
from app.token_usage import TokenUsageService


async def test_service_aggregates_by_model_and_resets(db_session: AsyncSession) -> None:
    service = TokenUsageService(db_session)
    await service.record(
        model="model-a",
        input_cache_hit_tokens=10,
        input_cache_miss_tokens=20,
        output_tokens=5,
    )
    await service.record(
        model="model-a",
        input_cache_hit_tokens=4,
        input_cache_miss_tokens=6,
        output_tokens=3,
    )
    await service.record(
        model="model-b",
        input_cache_hit_tokens=0,
        input_cache_miss_tokens=8,
        output_tokens=2,
    )

    summary = await service.summarize(["model-a", "unused-model"])

    assert [item.model for item in summary] == ["model-a", "unused-model", "model-b"]
    assert summary[0].input_cache_hit_tokens == 14
    assert summary[0].input_cache_miss_tokens == 26
    assert summary[0].input_tokens == 40
    assert summary[0].output_tokens == 8
    assert summary[0].total_tokens == 48
    assert summary[1].total_tokens == 0

    await service.reset()

    count = await db_session.scalar(select(func.count()).select_from(TokenUsageEvent))
    assert count == 0


async def test_token_usage_api_lists_models_and_reset_clears_events(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    engine = create_database_engine(api_settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await TokenUsageService(session).record(
            model="deepseek-v4-flash",
            input_cache_hit_tokens=30,
            input_cache_miss_tokens=70,
            output_tokens=25,
        )

    response = await api_client.get("/api/llm/token-usage")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["models"][0] == {
        "model": "deepseek-v4-flash",
        "input_cache_hit_tokens": 30,
        "input_cache_miss_tokens": 70,
        "input_tokens": 100,
        "output_tokens": 25,
        "total_tokens": 125,
    }
    assert data["total"]["total_tokens"] == 125

    reset_response = await api_client.delete("/api/llm/token-usage")

    assert reset_response.status_code == 200
    reset_data = reset_response.json()["data"]
    assert reset_data["total"]["total_tokens"] == 0
    assert all(item["total_tokens"] == 0 for item in reset_data["models"])

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(TokenUsageEvent))
    assert count == 0
    await engine.dispose()
