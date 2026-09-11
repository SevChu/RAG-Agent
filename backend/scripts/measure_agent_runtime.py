"""Synthetic in-memory runtime overhead.

Run from backend: python -m scripts.measure_agent_runtime.

No .env, persisted database, model gateway, model loading or external requests are used.
Measures configuration resolution only, not generation latency or production throughput.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from statistics import median
from time import perf_counter
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.configuration import AgentConfiguration
from app.agents.runtime import resolve_agent_runtime
from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_database_engine
from app.models import Conversation, Course
from app.repositories.agent_profile import AgentProfileRepository


async def measure(profile_count: int, samples: int) -> list[dict[str, Any]]:
    settings = Settings(
        _env_file=None,
        llm_api_key="fixture-never-send",
        llm_model="fixture-model",
        llm_available_models="fixture-model",
        qwen_models="",
        kimi_models="",
        glm_models="",
    )
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            courses = [Course(name=f"synthetic-{i}") for i in range(100)]
            session.add_all(courses)
            await session.flush()
            repository = AgentProfileRepository(session)
            targets = []
            for i in range(profile_count):
                config = AgentConfiguration.model_validate(
                    {
                        "model": {"provider": "deepseek", "model": "fixture-model"},
                        "allowed_course_ids": [course.id for course in courses] if i == 1 else [],
                    }
                )
                profile = await repository.create(
                    name=f"synthetic-{i}", description=None, enabled=True
                )
                revision = await repository.append(
                    profile.id, number=1, config=config, summary="synthetic"
                )
                if i < 2:
                    targets.append(
                        Conversation(
                            agent_profile_id=profile.id, agent_profile_revision_id=revision.id
                        )
                    )
            await session.commit()
        queries = 0

        def count(*args: Any) -> None:
            nonlocal queries
            queries += 1

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        results = []
        cases = [
            ("legacy", None, False, 0),
            ("bound_empty", targets[0], False, 1),
            ("bound_100_spaces", targets[1], False, 2),
            ("new_100_spaces", targets[1], True, 2),
        ]
        for name, conversation, creating, expected_queries in cases:
            timings = []
            counts = []
            for iteration in range(samples + 10):
                # Fresh session avoids reusing an ORM identity-map between simulated requests.
                async with factory() as session:
                    before = queries
                    started = perf_counter()
                    runtime = await resolve_agent_runtime(
                        session,
                        settings,
                        conversation=None if creating else conversation,
                        profile_id=(
                            conversation.agent_profile_id
                            if creating and conversation is not None
                            else None
                        ),
                    )
                    elapsed = (perf_counter() - started) * 1000
                    assert runtime.model == "fixture-model"
                    assert queries - before == expected_queries
                    if iteration >= 10:
                        timings.append(elapsed)
                        counts.append(queries - before)
            ordered = sorted(timings)
            results.append(
                {
                    "case": name,
                    "profiles": profile_count,
                    "samples": samples,
                    "sql_per_resolution": sorted(set(counts)),
                    "median_ms": round(median(timings), 3),
                    "p95_ms": round(ordered[math.ceil(samples * 0.95) - 1], 3),
                }
            )
        return results
    finally:
        await engine.dispose()


async def main(samples: int) -> None:
    results = []
    for size in (2, 1000):
        results.extend(await measure(size, samples))
    print(
        json.dumps(
            {
                "database": "synthetic SQLite in-memory",
                "warmup_per_case": 10,
                "scope": "resolution only; excludes session setup, retrieval and generation",
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=100)
    args = parser.parse_args()
    if not 10 <= args.samples <= 10000:
        parser.error("samples must be between 10 and 10000")
    asyncio.run(main(args.samples))
