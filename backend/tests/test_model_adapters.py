from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.core.exceptions import InvalidInputError
from app.training.adapter_service import AdapterService
from app.training.adapter_storage import AdapterStorage
from app.training.worker import TrainingWorker
from tests.test_training_datasets import review
from tests.test_training_runs import configure as configure
from tests.test_training_runs import create, get, payload
from tests.test_training_runs import sessions as sessions

ROOT = "/api/model-adapters"


async def completed(client: AsyncClient, settings: Settings, factory: Any) -> tuple[Any, Any, Any]:
    data = await payload(client)
    run = await create(client, data)
    assert await TrainingWorker(settings, factory).run_once()
    assert (await get(client, run["id"]))["status"] == "succeeded"
    response = await client.post(ROOT + "/from-run/" + run["id"])
    assert response.status_code == 200, response.text
    return data, run, response.json()["data"]


async def test_success_has_unique_manifest_and_safe_frozen_lineage(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    data, run, adapter = await completed(api_client, api_settings, sessions)
    manifest = adapter["manifest"]
    assert adapter["integrity"] == "valid" and adapter["deployable"] is False
    assert manifest["result"]["evaluation_status"] == "not_evaluated"
    assert manifest["source"]["request"]["dataset_revision_id"] == data["dataset_revision_id"]
    assert "版本一提示" not in json.dumps(adapter, ensure_ascii=False)
    assert "idempotency_key" not in manifest["source"]["request"]
    results = await asyncio.gather(
        *[api_client.post(ROOT + "/from-run/" + run["id"]) for _ in range(3)]
    )
    assert all(r.status_code == 200 and r.json()["data"] == adapter for r in results)
    assert len((await api_client.get(ROOT)).json()["data"]) == 1
    path = AdapterStorage(api_settings.training_data_dir / "adapters").path(UUID(adapter["id"]))
    assert json.loads(path.read_bytes()) == manifest
    assert list(path.parent.iterdir()) == [path]
    await review(api_client, data["dataset_id"], data["dataset_revision_id"], 4, "revoked")
    deleted = await api_client.delete(
        "/api/agent-profiles/" + data["agent_profile_id"], params={"expected_row_version": 1}
    )
    assert deleted.status_code == 200
    assert (await api_client.get(ROOT + "/" + adapter["id"])).json()["data"] == adapter


@pytest.mark.parametrize("damage", ["missing", "changed", "oversize", "hardlink"])
async def test_file_damage_is_visible_and_never_silently_repaired(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    damage: str,
) -> None:
    _, run, adapter = await completed(api_client, api_settings, sessions)
    path = AdapterStorage(api_settings.training_data_dir / "adapters").path(UUID(adapter["id"]))
    if damage == "missing":
        path.unlink()
    elif damage == "changed":
        path.write_bytes(b"{}")
    elif damage == "oversize":
        path.write_bytes(b"x" * (128 * 1024 + 1))
    else:
        os.link(path, path.with_suffix(".alias"))
    item = (await api_client.get(ROOT + "/" + adapter["id"])).json()["data"]
    assert item["integrity"] == ("missing" if damage == "missing" else "invalid")
    assert item["deployable"] is False
    assert (await api_client.post(ROOT + "/from-run/" + run["id"])).status_code == 400
    assert (await get(api_client, run["id"]))["status"] == "succeeded"


async def test_file_then_database_failure_rolls_back_success_and_reports_orphan(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = AdapterService.register

    async def fail_after_file(self: AdapterService, run: Any) -> Any:
        await original(self, run)
        raise RuntimeError("private database failure marker")

    monkeypatch.setattr(AdapterService, "register", fail_after_file)
    run = await create(api_client, await payload(api_client))
    await TrainingWorker(api_settings, sessions).run_once()
    assert (await get(api_client, run["id"]))["status"] == "failed"
    assert (await api_client.get(ROOT)).json()["data"] == []
    audit = (await api_client.get(ROOT + "/storage-audit")).json()["data"]
    assert audit["unregistered_file_ids"] == [str(AdapterService.identity(UUID(run["id"])))]
    monkeypatch.setattr(AdapterService, "register", original)
    assert (await api_client.post(ROOT + "/from-run/" + run["id"])).status_code == 400


async def test_successful_legacy_run_reconciles_without_retraining_and_reuses_file(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = AdapterService.register

    async def legacy(self: AdapterService, run: Any) -> Any:
        return None

    monkeypatch.setattr(AdapterService, "register", legacy)
    data = await payload(api_client)
    run = await create(api_client, data)
    await TrainingWorker(api_settings, sessions).run_once()
    before = await get(api_client, run["id"])
    assert before["status"] == "succeeded"
    monkeypatch.setattr(AdapterService, "register", original)
    # Simulate failed registry commit after file promotion; original succeeded run persists.
    async with sessions() as session:
        from app.models import TrainingRun
        from app.training.run_store import RunStore

        with pytest.raises(RuntimeError):
            async with RunStore(session, api_settings).transaction():
                model = await session.get(TrainingRun, UUID(run["id"]))
                assert model is not None
                await original(AdapterService(session, api_settings), model)
                raise RuntimeError("commit aborted")
    path = AdapterStorage(api_settings.training_data_dir / "adapters").path(
        AdapterService.identity(UUID(run["id"]))
    )
    before_stat = path.stat().st_mtime_ns
    await review(api_client, data["dataset_id"], data["dataset_revision_id"], 4, "revoked")
    response = await api_client.post(ROOT + "/from-run/" + run["id"])
    assert response.status_code == 200, response.text
    assert path.stat().st_mtime_ns == before_stat
    assert (await get(api_client, run["id"])) == before
    assert (await api_client.get(ROOT + "/storage-audit")).json()["data"][
        "unregistered_file_ids"
    ] == []


async def test_promotion_failure_leaves_no_adapter_or_success(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*args: Any) -> None:
        raise OSError("private disk path")

    monkeypatch.setattr(os, "rename", denied)
    run = await create(api_client, await payload(api_client))
    await TrainingWorker(api_settings, sessions).run_once()
    assert (await get(api_client, run["id"]))["status"] == "failed"
    assert (await api_client.get(ROOT)).json()["data"] == []
    assert (await api_client.get(ROOT + "/storage-audit")).json()["data"]["staged_files"] == 1


async def test_predecessor_lineage_archive_and_parameter_compatibility(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    data, _, first = await completed(api_client, api_settings, sessions)
    data.update(idempotency_key=uuid4().hex, predecessor_adapter_id=first["id"])
    run = await create(api_client, data)
    await TrainingWorker(api_settings, sessions).run_once()
    second = (await api_client.post(ROOT + "/from-run/" + run["id"])).json()["data"]
    assert second["predecessor_id"] == first["id"]
    chain = (await api_client.get(ROOT + "/" + second["id"] + "/lineage")).json()["data"]
    assert [item["id"] for item in chain["items"]] == [second["id"], first["id"]]
    short = (
        await api_client.get(ROOT + "/" + second["id"] + "/lineage", params={"limit": 1})
    ).json()["data"]
    assert short["next_predecessor_id"] == first["id"]
    source = second["manifest"]["source"]["request"]
    config = {k: source[k] for k in ("target", "base_model", "base_model_revision", "parameters")}
    config["dataset_schema_version"] = 1
    result = (
        await api_client.post(ROOT + "/" + second["id"] + "/compatibility", json=config)
    ).json()["data"]
    assert result["contract_compatible"] and not result["deployable"]
    config["base_model_revision"] = "different"
    result = (
        await api_client.post(ROOT + "/" + second["id"] + "/compatibility", json=config)
    ).json()["data"]
    assert not result["contract_compatible"] and "BASE_MODEL_REVISION_MISMATCH" in result["reasons"]
    for _ in range(2):
        assert (await api_client.post(ROOT + "/" + first["id"] + "/archive")).status_code == 200
    assert len((await api_client.get(ROOT)).json()["data"]) == 1
    assert len((await api_client.get(ROOT, params={"include_archived": True})).json()["data"]) == 2
    assert (
        await api_client.post("/api/training-runs", json={**data, "idempotency_key": uuid4().hex})
    ).status_code == 400


@pytest.mark.parametrize("place", ["root", "model", "retrieval"])
async def test_simulated_adapter_cannot_enter_runtime_configuration(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
    place: str,
) -> None:
    _, _, adapter = await completed(api_client, api_settings, sessions)
    config: dict[str, Any] = {"model": {"provider": "deepseek", "model": "model-a"}}
    if place == "root":
        config["adapter_id"] = adapter["id"]
    else:
        config.setdefault(place, {})["adapter_id"] = adapter["id"]
    assert (
        await api_client.post("/api/agent-profiles", json={"name": "invalid", "config": config})
    ).status_code == 422


async def test_database_identity_and_archive_guards(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    _, _, adapter = await completed(api_client, api_settings, sessions)
    db = api_settings.database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(db) as conn:
        for sql in (
            "UPDATE model_adapters SET deployable=1",
            "DELETE FROM model_adapters",
            "UPDATE model_adapters SET manifest='{}'",
            "UPDATE model_adapters SET predecessor_id=id",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)
    await api_client.post(ROOT + "/" + adapter["id"] + "/archive")
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE model_adapters SET archived_at=NULL")


async def test_product_guard_and_request_bound(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    _, run, adapter = await completed(api_client, api_settings, sessions)
    assert (
        await api_client.post(ROOT + "/" + adapter["id"] + "/compatibility", content=b"x" * 65537)
    ).status_code == 413
    api_settings.agentic_edition = "product"
    for suffix in ("", "/storage-audit", "/" + adapter["id"], "/" + adapter["id"] + "/lineage"):
        assert (await api_client.get(ROOT + suffix)).status_code == 403
    for suffix in ("/from-run/" + run["id"], "/" + adapter["id"] + "/archive"):
        assert (await api_client.post(ROOT + suffix)).status_code == 403


def test_storage_rejects_symbolic_link(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit symlinks")
    with pytest.raises(InvalidInputError):
        AdapterStorage(link).promote(uuid4(), b"{}")


async def test_incompatible_predecessor_and_cancelled_run_rejected(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    data, _, adapter = await completed(api_client, api_settings, sessions)
    copied = await api_client.post(
        "/api/agent-profiles/" + data["agent_profile_id"] + "/copy",
        json={"name": "不同的合成智能体"},
    )
    assert copied.status_code == 201
    other = {
        **data,
        "agent_profile_id": copied.json()["data"]["id"],
        "idempotency_key": uuid4().hex,
    }
    invalid = {**other, "predecessor_adapter_id": adapter["id"]}
    assert (await api_client.post("/api/training-runs", json=invalid)).status_code == 400
    queued = await create(api_client, other)
    await api_client.post("/api/training-runs/" + queued["id"] + "/cancel")
    assert (await api_client.post(ROOT + "/from-run/" + queued["id"])).status_code == 400
    assert len((await api_client.get(ROOT)).json()["data"]) == 1


async def test_forged_success_checksum_never_registers(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    from app.training.trainer import FakeTrainer

    class ForgedTrainer(FakeTrainer):
        async def run(self, snapshot: Any, progress: Any) -> Any:
            result = await super().run(snapshot, progress)
            assert result is not None
            result["simulation_checksum"] = "0" * 64
            return result

    run = await create(api_client, await payload(api_client))
    await TrainingWorker(api_settings, sessions, ForgedTrainer(0.01)).run_once()
    assert (await get(api_client, run["id"]))["status"] == "failed"
    assert (await api_client.get(ROOT)).json()["data"] == []
    assert not (api_settings.training_data_dir / "adapters").exists()


async def test_database_rejects_duplicate_and_non_success_registration(
    api_client: AsyncClient,
    api_settings: Settings,
    sessions: Any,
) -> None:
    data, _, adapter = await completed(api_client, api_settings, sessions)
    queued = await create(api_client, {**data, "idempotency_key": uuid4().hex})
    db = api_settings.database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT OR REPLACE INTO model_adapters SELECT * FROM model_adapters")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO model_adapters (id,run_id,manifest,manifest_sha256) VALUES (?,?,?,?)",
                (
                    uuid4().hex,
                    UUID(queued["id"]).hex,
                    json.dumps(adapter["manifest"]),
                    adapter["manifest_sha256"],
                ),
            )
