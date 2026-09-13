from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import create_database_engine
from app.training.run_store import RunStore
from app.training.trainer import FakeTrainer, simulation_checksum
from app.training.worker import TrainingWorker
from tests.test_agent_runtime import profile
from tests.test_training_datasets import MANIFEST, approved, review

ROOT = "/api/training-runs"


@pytest.fixture(autouse=True)
def configure(api_settings: Settings, tmp_path: Path) -> None:
    api_settings.agentic_edition = "research"
    api_settings.training_data_dir = tmp_path / "training"
    api_settings.training_fake_step_seconds = 0.01
    api_settings.training_poll_interval_seconds = 0.05
    api_settings.training_lease_seconds = 1
    api_settings.llm_api_key = "fixture-never-send"
    api_settings.llm_model = "model-a"
    api_settings.llm_available_models = "model-a"


@pytest_asyncio.fixture
async def sessions(api_client: AsyncClient, api_settings: Settings) -> Any:
    engine = create_database_engine(api_settings.database_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def payload(client: AsyncClient, *, scoped: bool = False) -> dict[str, Any]:
    manifest = deepcopy(MANIFEST)
    spaces = []
    if scoped:
        course = (await client.post("/api/courses", json={"name": "合成训练来源"})).json()["data"]
        spaces = [course["id"]]
        manifest["source_course_ids"] = spaces
    agent = await profile(client, allowed_course_ids=spaces)
    did, rid = await approved(client, manifest=manifest)
    return {
        "idempotency_key": uuid4().hex,
        "agent_profile_id": agent["id"],
        "dataset_id": did,
        "dataset_revision_id": rid,
        "target": "reranker",
        "base_model": "fake-reranker-v1",
        "simulation_steps": 3,
    }


async def create(client: AsyncClient, data: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(ROOT, json=data)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def get(client: AsyncClient, run_id: str) -> dict[str, Any]:
    response = await client.get(ROOT + "/" + run_id)
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


async def call(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    method: str,
    *args: Any,
    clock: Any = time.time,
    **kwargs: Any,
) -> Any:
    async with factory() as session:
        return await getattr(RunStore(session, settings, clock), method)(*args, **kwargs)


async def wait_for(
    client: AsyncClient, run_id: str, *, state: str = "running", step: int = 0
) -> dict[str, Any]:
    async with asyncio.timeout(8):
        while True:
            run = await get(client, run_id)
            if run["status"] == state and run["completed_steps"] >= step:
                return run
            await asyncio.sleep(0.01)


async def test_success_persists_events_and_deterministic_result(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    data = await payload(api_client)
    run = await create(api_client, data)
    assert run["status"] == "queued"
    assert "agent_configuration" not in run["source"]
    assert "idempotency_key" not in run["source"]["request"]
    worker = TrainingWorker(api_settings, sessions)
    assert await worker.run_once()
    completed = await get(api_client, run["id"])
    assert completed["status"] == "succeeded" and completed["completed_steps"] == 3
    assert completed["result"]["deployable"] is False
    assert completed["result"]["evaluation_status"] == "not_evaluated"
    events = (await api_client.get(f"{ROOT}/{run['id']}/events")).json()["data"]
    assert [item["sequence"] for item in events] == list(range(1, 7))
    assert [item["phase"] for item in events] == [
        "queued",
        "running",
        "running",
        "running",
        "running",
        "succeeded",
    ]
    assert "版本一提示" not in json.dumps(events, ensure_ascii=False)
    tail = (
        await api_client.get(f"{ROOT}/{run['id']}/events", params={"after": 4, "limit": 1})
    ).json()["data"]
    assert tail[0]["sequence"] == 5
    other = await create(api_client, {**data, "idempotency_key": uuid4().hex})
    assert await worker.run_once()
    assert (await get(api_client, other["id"]))["result"] == completed["result"]
    assert not await worker.run_once()


async def test_idempotency_concurrent_and_conflicting_requests(api_client: AsyncClient) -> None:
    data = await payload(api_client)
    results = await asyncio.gather(create(api_client, data), create(api_client, data))
    assert results[0]["id"] == results[1]["id"]
    conflict = await api_client.post(ROOT, json={**data, "simulation_steps": 4})
    assert conflict.status_code == 409
    assert len((await api_client.get(ROOT)).json()["data"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"trainer": "real"},
        {"base_model": "remote/model"},
        {"base_model": "fake-scorer-v1"},
        {"simulation_steps": 101},
        {"simulation_steps": True},
        {"fail_at": 1},
        {"parameters": {"rank": 0}},
        {"parameters": {"rank": True}},
        {"parameters": {"dropout": 1}},
        {"parameters": {"learning_rate": 0}},
        {"parameters": {"method": "full"}},
        {"idempotency_key": "bad"},
    ],
)
async def test_unsafe_or_unknown_training_contracts_rejected(
    api_client: AsyncClient,
    change: dict[str, Any],
) -> None:
    data = await payload(api_client)
    response = await api_client.post(ROOT, json={**data, **change})
    assert response.status_code == 422
    assert (await api_client.get(ROOT)).json()["data"] == []


async def test_estimate_is_explicitly_simulated_and_unknown_real_cost(
    api_client: AsyncClient,
) -> None:
    data = await payload(api_client)
    response = await api_client.post(ROOT + "/estimate", json=data)
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["mode"] == "simulated" and result["nominal_simulation_seconds"] == 0.03
    assert (
        result["real_training_seconds"] is result["real_vram_bytes"] is result["real_cost"] is None
    )
    assert (await api_client.get(ROOT)).json()["data"] == []
    assert (await api_client.get(ROOT + "/options")).json()["data"]["worker_enabled"] is False


async def test_queue_cancel_and_terminal_idempotency(
    api_client: AsyncClient, api_settings: Settings, sessions: Any
) -> None:
    run = await create(api_client, await payload(api_client))
    for _ in range(2):
        result = (await api_client.post(f"{ROOT}/{run['id']}/cancel")).json()["data"]
        assert result["status"] == "cancelled"
    assert not await TrainingWorker(api_settings, sessions).run_once()
    assert len((await api_client.get(f"{ROOT}/{run['id']}/events")).json()["data"]) == 2


async def test_running_cancel_at_checkpoint(
    api_client: AsyncClient, api_settings: Settings, sessions: Any, tmp_path: Path
) -> None:
    data = await payload(api_client)
    run = await create(api_client, {**data, "simulation_steps": 50})
    worker = TrainingWorker(api_settings, sessions, FakeTrainer(0.03))
    execution = asyncio.create_task(worker.run_once())
    await wait_for(api_client, run["id"], step=1)
    start = time.monotonic()
    response = await api_client.post(f"{ROOT}/{run['id']}/cancel")
    assert response.json()["data"]["status"] == "cancelling"
    await execution
    final = await get(api_client, run["id"])
    assert final["status"] == "cancelled" and final["result"] is None
    assert final["completed_steps"] < 50
    elapsed = time.monotonic() - start
    assert elapsed < 2
    (tmp_path / "cancel-metrics.json").write_text(
        json.dumps(
            {
                "checkpoint_seconds": 0.03,
                "cancel_to_terminal_seconds": elapsed,
                "completed_steps": final["completed_steps"],
                "total_steps": 50,
            }
        ),
        encoding="utf-8",
    )


async def test_failure_redacted_and_retry_preserves_frozen_revision(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    data = await payload(api_client)
    run = await create(api_client, data)
    assert await TrainingWorker(api_settings, sessions, FakeTrainer(0.01, fail_at=1)).run_once()
    failed = await get(api_client, run["id"])
    assert failed["status"] == "failed" and failed["last_code"] == "TRAINER_FAILED"
    agent = (await api_client.get("/api/agent-profiles/" + data["agent_profile_id"])).json()["data"]
    config = deepcopy(agent["current_revision"]["config"])
    config["system_prompt"] = "新版本不影响重试来源"
    assert (
        await api_client.patch(
            "/api/agent-profiles/" + agent["id"], json={"expected_row_version": 1, "config": config}
        )
    ).status_code == 200
    key = {"idempotency_key": uuid4().hex}
    retry = await api_client.post(f"{ROOT}/{run['id']}/retry", json=key)
    assert retry.status_code == 201, retry.text
    new = retry.json()["data"]
    assert new["id"] != run["id"] and new["retry_of"] == run["id"]
    assert new["agent_revision_id"] == run["agent_revision_id"]
    assert (await api_client.post(f"{ROOT}/{run['id']}/retry", json=key)).json()["data"][
        "id"
    ] == new["id"]
    assert await TrainingWorker(api_settings, sessions).run_once()
    assert (await get(api_client, new["id"]))["status"] == "succeeded"
    assert (await get(api_client, run["id"])) == failed
    assert (
        await api_client.post(f"{ROOT}/{new['id']}/retry", json={"idempotency_key": uuid4().hex})
    ).status_code == 409


async def test_two_workers_claim_once(
    api_client: AsyncClient, api_settings: Settings, sessions: Any
) -> None:
    await create(api_client, await payload(api_client))
    one, two = (
        TrainingWorker(api_settings, sessions, FakeTrainer(0.05)),
        TrainingWorker(api_settings, sessions),
    )
    results = await asyncio.gather(one.run_once(), two.run_once())
    assert sorted(results) == [False, True]


async def test_expired_lease_recovers_and_fences_late_callbacks(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    data = await payload(api_client)
    first = await create(api_client, data)
    clock = [time.time()]
    claimed = await call(sessions, api_settings, "claim", clock=lambda: clock[0])
    rid, token, _ = claimed
    assert str(rid) == first["id"]
    assert not await call(sessions, api_settings, "claim", clock=lambda: clock[0])
    clock[0] += 2
    assert not await call(sessions, api_settings, "claim", clock=lambda: clock[0])
    assert (await get(api_client, first["id"]))["status"] == "interrupted"
    assert not await call(sessions, api_settings, "progress", rid, token, 1, clock=lambda: clock[0])
    assert not await call(
        sessions, api_settings, "finish", rid, token, None, clock=lambda: clock[0]
    )
    assert not await call(sessions, api_settings, "renew", token, clock=lambda: clock[0])


async def test_heartbeat_preserves_slow_live_owner(
    api_client: AsyncClient, api_settings: Settings, sessions: Any
) -> None:
    run = await create(api_client, {**await payload(api_client), "simulation_steps": 1})
    worker = TrainingWorker(api_settings, sessions, FakeTrainer(1.3))
    execution = asyncio.create_task(worker.run_once())
    await wait_for(api_client, run["id"])
    await asyncio.sleep(1.1)
    assert not await call(sessions, api_settings, "claim")
    await execution
    assert (await get(api_client, run["id"]))["status"] == "succeeded"


async def test_graceful_shutdown_marks_interrupted(
    api_client: AsyncClient, api_settings: Settings, sessions: Any
) -> None:
    run = await create(api_client, {**await payload(api_client), "simulation_steps": 100})
    worker = TrainingWorker(api_settings, sessions, FakeTrainer(0.1))
    worker.start()
    await wait_for(api_client, run["id"])
    await worker.close()
    result = await get(api_client, run["id"])
    assert result["status"] == "interrupted" and result["last_code"] == "WORKER_SHUTDOWN"


@pytest.mark.parametrize("cause", ["review", "disabled", "deleted", "scope", "course"])
@pytest.mark.parametrize("running", [False, True])
async def test_dependency_revocation_is_transactional(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    cause: str,
    running: bool,
) -> None:
    data = await payload(api_client, scoped=True)
    run = await create(api_client, data)
    claimed = await call(sessions, api_settings, "claim") if running else None
    agent_url = "/api/agent-profiles/" + data["agent_profile_id"]
    if cause == "review":
        response = await review(
            api_client, data["dataset_id"], data["dataset_revision_id"], 4, "revoked"
        )
    elif cause == "deleted":
        response = await api_client.delete(agent_url, params={"expected_row_version": 1})
    elif cause == "disabled":
        response = await api_client.patch(
            agent_url, json={"expected_row_version": 1, "enabled": False}
        )
    else:
        agent = (await api_client.get(agent_url)).json()["data"]
        config = deepcopy(agent["current_revision"]["config"])
        if cause == "course":
            response = await api_client.delete("/api/courses/" + config["allowed_course_ids"][0])
        else:
            config["allowed_course_ids"] = []
            response = await api_client.patch(
                agent_url, json={"expected_row_version": 1, "config": config}
            )
    assert response.status_code == 200, response.text
    assert (await get(api_client, run["id"]))["status"] == (
        "cancelling" if running else "cancelled"
    )
    if claimed:
        rid, token, _ = claimed
        assert not await call(sessions, api_settings, "progress", rid, token, 1)
        assert await call(
            sessions,
            api_settings,
            "finish",
            rid,
            token,
            {"artifact_kind": "simulated", "deployable": False},
        )
        assert (await get(api_client, run["id"]))["status"] == "cancelled"
    assert (
        await api_client.post(ROOT, json={**data, "idempotency_key": uuid4().hex})
    ).status_code == 400
    assert (
        await api_client.post(f"{ROOT}/{run['id']}/retry", json={"idempotency_key": uuid4().hex})
    ).status_code == 400


@pytest.mark.parametrize("timing", ["before_claim", "before_finish"])
async def test_tampering_prevents_success(
    api_client: AsyncClient, api_settings: Settings, sessions: Any, timing: str
) -> None:
    data = await payload(api_client)
    run = await create(api_client, data)
    claimed = await call(sessions, api_settings, "claim") if timing == "before_finish" else None
    path = api_settings.training_data_dir / (UUID(data["dataset_revision_id"]).hex + ".jsonl")
    path.write_bytes(path.read_bytes() + b" ")
    if claimed:
        rid, token, _ = claimed
        for step in (1, 2, 3):
            assert await call(sessions, api_settings, "progress", rid, token, step)
        await call(
            sessions,
            api_settings,
            "finish",
            rid,
            token,
            {"artifact_kind": "simulated", "deployable": False},
        )
        assert (await get(api_client, run["id"]))["status"] == "failed"
    else:
        assert not await call(sessions, api_settings, "claim")
        assert (await get(api_client, run["id"]))["status"] == "cancelled"


async def test_invalid_progress_and_sql_overwrites_rejected(
    api_client: AsyncClient, api_settings: Settings, sessions: Any
) -> None:
    run = await create(api_client, await payload(api_client))
    rid, token, _ = await call(sessions, api_settings, "claim")
    from app.core.exceptions import InvalidInputError

    with pytest.raises(InvalidInputError):
        await call(sessions, api_settings, "progress", rid, token, 2)
    assert await call(sessions, api_settings, "progress", rid, token, 1)
    with pytest.raises(InvalidInputError):
        await call(sessions, api_settings, "progress", rid, token, 0)
    path = api_settings.database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(path) as conn:
        for sql in (
            "UPDATE training_runs SET total_steps=4",
            "UPDATE training_runs SET status='queued'",
            "DELETE FROM training_runs",
            "INSERT OR REPLACE INTO training_runs SELECT * FROM training_runs",
            "UPDATE training_events SET code='changed'",
            "DELETE FROM training_events",
            "INSERT OR REPLACE INTO training_events SELECT * FROM training_events",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)
    await api_client.post(f"{ROOT}/{run['id']}/cancel")
    await call(sessions, api_settings, "finish", rid, token, None)
    assert not await call(sessions, api_settings, "progress", rid, token, 2)


async def test_product_rejects_all_task_routes(
    api_client: AsyncClient, api_settings: Settings
) -> None:
    data = await payload(api_client)
    run = await create(api_client, data)
    api_settings.agentic_edition = "product"
    for suffix in ("", "/options", "/" + run["id"], "/" + run["id"] + "/events"):
        assert (await api_client.get(ROOT + suffix)).status_code == 403
    for suffix, body in (
        ("", data),
        ("/estimate", data),
        ("/" + run["id"] + "/cancel", {}),
        ("/" + run["id"] + "/retry", {"idempotency_key": uuid4().hex}),
    ):
        assert (await api_client.post(ROOT + suffix, json=body)).status_code == 403


async def test_run_body_limit(api_client: AsyncClient) -> None:
    response = await api_client.post(
        ROOT, content=b"x" * 65537, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


@pytest.mark.parametrize("cancel_kind", ["user", "review"])
async def test_cancel_racing_completion_never_overwrites_terminal(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    cancel_kind: str,
) -> None:
    data = await payload(api_client)
    run = await create(api_client, data)
    rid, token, snapshot = await call(sessions, api_settings, "claim")
    for step in (1, 2, 3):
        await call(sessions, api_settings, "progress", rid, token, step)
    cancel = (
        api_client.post(f"{ROOT}/{run['id']}/cancel")
        if cancel_kind == "user"
        else review(api_client, data["dataset_id"], data["dataset_revision_id"], 4, "revoked")
    )
    finished, response = await asyncio.gather(
        call(
            sessions,
            api_settings,
            "finish",
            rid,
            token,
            {
                "artifact_kind": "simulated",
                "deployable": False,
                "evaluation_status": "not_evaluated",
                "trainer": "fake-v1",
                "simulation_checksum": simulation_checksum(snapshot),
            },
        ),
        cancel,
    )
    assert response.status_code == 200
    state = (await get(api_client, run["id"]))["status"]
    assert state in {"succeeded", "cancelled"}
    events = (await api_client.get(f"{ROOT}/{run['id']}/events")).json()["data"]
    phases = [item["phase"] for item in events]
    if "cancelling" in phases:
        assert phases[-1] == "cancelled" and "succeeded" not in phases
    assert not await call(sessions, api_settings, "finish", rid, token, None)
    assert (await get(api_client, run["id"]))["status"] == state


async def test_revocation_racing_admission_cannot_leave_runnable_job(
    api_client: AsyncClient,
) -> None:
    data = await payload(api_client)
    admitted, revoked = await asyncio.gather(
        api_client.post(ROOT, json=data),
        review(api_client, data["dataset_id"], data["dataset_revision_id"], 4, "revoked"),
    )
    assert revoked.status_code == 200, revoked.text
    assert admitted.status_code in {201, 400}
    if admitted.status_code == 201:
        assert (await get(api_client, admitted.json()["data"]["id"]))["status"] == "cancelled"


async def test_failure_does_not_publish_exception_body(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingTrainer(FakeTrainer):
        async def run(self, snapshot: Any, progress: Any) -> Any:
            raise RuntimeError("private-marker-api-key synthetic/customer/path")

    run = await create(api_client, await payload(api_client))
    await TrainingWorker(api_settings, sessions, FailingTrainer()).run_once()
    result = await get(api_client, run["id"])
    events = (await api_client.get(f"{ROOT}/{run['id']}/events")).text
    assert result["status"] == "failed" and result["last_code"] == "TRAINER_FAILED"
    assert "private-marker" not in json.dumps(result) + events + caplog.text


async def test_reapproval_does_not_resurrect_cancelled_run(api_client: AsyncClient) -> None:
    data = await payload(api_client)
    run = await create(api_client, data)
    for version, state in ((4, "revoked"), (5, "pending_review"), (6, "approved")):
        result = await review(
            api_client, data["dataset_id"], data["dataset_revision_id"], version, state
        )
        assert result.status_code == 200, result.text
    assert (await get(api_client, run["id"]))["status"] == "cancelled"
    retried = await api_client.post(
        f"{ROOT}/{run['id']}/retry", json={"idempotency_key": uuid4().hex}
    )
    assert retried.status_code == 201 and retried.json()["data"]["status"] == "queued"


async def test_lifespan_starts_only_enabled_research_worker(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.db.session as database
    import app.main as main

    class IndexingStub:
        async def close(self) -> None:
            pass

    run = await create(api_client, await payload(api_client))
    api_settings.training_worker_enabled = True
    monkeypatch.setattr(main, "settings", api_settings)
    monkeypatch.setattr(main, "indexing_manager", IndexingStub())
    monkeypatch.setattr(database, "SessionFactory", sessions)
    async with main.lifespan(main.app):
        await wait_for(api_client, run["id"], state="succeeded")


async def test_mismatched_dataset_target_cannot_be_submitted(api_client: AsyncClient) -> None:
    data = await payload(api_client)
    response = await api_client.post(
        ROOT, json={**data, "target": "scorer", "base_model": "fake-scorer-v1"}
    )
    assert response.status_code == 400
