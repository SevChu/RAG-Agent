from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import AsyncClient

from app.core.config import Settings, get_settings
from app.generation import get_chat_completion_gateway
from app.main import app
from tests.test_agent_runtime import RecordingGateway, profile, quick
from tests.test_qa_api import _sse_event_data


@pytest.fixture(autouse=True)
def configured(api_settings: Settings) -> None:
    api_settings.llm_api_key = "fixture-never-send"
    api_settings.llm_available_models = "model-a"
    api_settings.llm_model = "model-a"
    api_settings.qwen_models = api_settings.kimi_models = api_settings.glm_models = ""


async def test_delete_preserves_history_and_blocks_all_writes(api_client: AsyncClient) -> None:
    gateway = RecordingGateway()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    original = await profile(api_client)
    conv = await quick(api_client, original["id"])
    chat = f"/api/quick-conversations/{conv['id']}"
    response = await api_client.post(
        chat + "/messages/stream", json={"message": "合成历史", "web_search": False}
    )
    assert _sse_event_data(response.text, "complete")["agent_runtime"]["revision_number"] == 1
    before = (await api_client.get(chat)).json()["data"]
    root = f"/api/agent-profiles/{original['id']}"
    revision = original["current_revision"]
    deleted = await api_client.delete(root, params={"expected_row_version": 1})
    assert deleted.status_code == 200
    current = (await api_client.get(root)).json()["data"]
    assert current["deleted_at"] is not None and current["enabled"] is False
    assert current["row_version"] == 2
    assert current["name"] == original["name"]
    assert current["current_revision"] == revision
    for filters in ({}, {"enabled": False}, {"enabled": True}):
        assert (await api_client.get("/api/agent-profiles", params=filters)).json()["data"] == []
    assert (await api_client.get(root + "/revisions")).json()["data"] == [revision]
    assert (await api_client.get(root + f"/revisions/{revision['id']}")).json()["data"] == revision
    assert (await api_client.get(chat)).json()["data"] == before
    assert (await api_client.delete(root, params={"expected_row_version": 1})).status_code == 200
    assert (await api_client.get(root)).json()["data"]["row_version"] == 2
    for path, payload in [
        ("/api/quick-conversations", {"agent_profile_id": original["id"]}),
        (chat + "/messages/stream", {"message": "禁止生成"}),
        (root + "/copy", {"name": "禁止复制"}),
        (root + "/restore", {"expected_row_version": 2, "revision_id": revision["id"]}),
    ]:
        result = await api_client.post(path, json=payload)
        assert result.status_code == 409, result.text
        assert "已删除" in result.text
    for change in ({"enabled": True}, {"config": revision["config"]}, {"name": "禁止改名"}):
        result = await api_client.patch(root, json={"expected_row_version": 2, **change})
        assert result.status_code == 409
    assert len(gateway.calls) == 1
    assert (await api_client.get(chat)).json()["data"] == before


async def test_delete_stale_version_missing_identity_and_invalid_version(
    api_client: AsyncClient,
) -> None:
    original = await profile(api_client)
    root = f"/api/agent-profiles/{original['id']}"
    assert (
        await api_client.patch(root, json={"expected_row_version": 1, "description": "并发编辑"})
    ).status_code == 200
    assert (await api_client.delete(root, params={"expected_row_version": 1})).status_code == 409
    current = (await api_client.get(root)).json()["data"]
    assert current["deleted_at"] is None and current["enabled"] is True
    for params in ({}, {"expected_row_version": 0}, {"expected_row_version": "bad"}):
        assert (await api_client.delete(root, params=params)).status_code == 422
    missing = f"/api/agent-profiles/{uuid4()}"
    assert (await api_client.delete(missing, params={"expected_row_version": 1})).status_code == 404


async def test_delete_does_not_require_valid_live_dependencies(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    original = await profile(api_client)
    api_settings.llm_api_key = ""
    result = await api_client.delete(
        f"/api/agent-profiles/{original['id']}", params={"expected_row_version": 1}
    )
    assert result.status_code == 200


def test_soft_delete_migration_preserves_populated_agent_and_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_agent_profiles import make_config

    path = tmp_path / "delete-migration.db"
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "20260907_05")
        pid, rid, cid = (uuid4().hex for _ in range(3))
        snapshot = make_config()
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO agent_profiles(id,name) VALUES (?,'合成迁移')", (pid,))
            db.execute(
                "INSERT INTO agent_profile_revisions"
                "(id,agent_profile_id,revision_number,config,config_sha256) VALUES (?,?,1,?,?)",
                (rid, pid, snapshot.canonical_json(), snapshot.sha256()),
            )
            db.execute(
                "INSERT INTO conversations(id,kind,agent_profile_id,agent_profile_revision_id)"
                " VALUES (?,'quick',?,?)",
                (cid, pid, rid),
            )
            old: dict[str, Any] = {
                table: db.execute(f"SELECT * FROM {table}").fetchall()
                for table in ("agent_profile_revisions", "conversations")
            }
        command.upgrade(config, "head")
        command.check(config)
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT deleted_at FROM agent_profiles").fetchone() == (None,)
            db.execute("UPDATE agent_profiles SET enabled=0,deleted_at=CURRENT_TIMESTAMP")
            for table, rows in old.items():
                assert db.execute(f"SELECT * FROM {table}").fetchall() == rows
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        command.downgrade(config, "20260907_05")
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT enabled FROM agent_profiles").fetchone() == (0,)
            for table, rows in old.items():
                assert db.execute(f"SELECT * FROM {table}").fetchall() == rows
        command.upgrade(config, "head")
        command.check(config)
    finally:
        get_settings.cache_clear()
