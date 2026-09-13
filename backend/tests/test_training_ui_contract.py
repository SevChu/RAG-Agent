from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.test_training_runs import configure as configure
from tests.test_training_runs import payload


async def test_explicit_stale_agent_revision_rejected_without_queued_task(
    api_client: AsyncClient,
) -> None:
    data = await payload(api_client)
    result = await api_client.post(
        "/api/training-runs", json={**data, "expected_agent_revision_id": str(uuid4())}
    )
    assert result.status_code == 409
    assert (await api_client.get("/api/training-runs")).json()["data"] == []


async def test_selected_revision_change_requires_review_but_keeps_created_snapshot(
    api_client: AsyncClient,
) -> None:
    data = await payload(api_client)
    path = "/api/agent-profiles/" + data["agent_profile_id"]
    agent = (await api_client.get(path)).json()["data"]
    selected = agent["current_revision"]["id"]
    good = await api_client.post(
        "/api/training-runs", json={**data, "expected_agent_revision_id": selected}
    )
    assert good.status_code == 201
    config: dict[str, Any] = agent["current_revision"]["config"]
    config["system_prompt"] = "用户复核后新的版本"
    assert (
        await api_client.patch(path, json={"expected_row_version": 1, "config": config})
    ).status_code == 200
    stale = await api_client.post(
        "/api/training-runs",
        json={**data, "idempotency_key": uuid4().hex, "expected_agent_revision_id": selected},
    )
    assert stale.status_code == 409
    old = (await api_client.get("/api/training-runs/" + good.json()["data"]["id"])).json()["data"]
    assert old["agent_revision_id"] == selected
    # Same-key replay still returns the original task after agent edits.
    replay = await api_client.post(
        "/api/training-runs", json={**data, "expected_agent_revision_id": selected}
    )
    assert replay.status_code == 201 and replay.json()["data"]["id"] == old["id"]
