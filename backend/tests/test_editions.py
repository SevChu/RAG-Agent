from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.core.distribution import DEFAULT_EDITION
from tests.test_agent_runtime import RecordingGateway, profile, quick
from tests.test_qa_api import _sse_event_data


@pytest.fixture(autouse=True)
def configured(api_settings: Settings) -> None:
    api_settings.agentic_edition = "product"
    api_settings.llm_api_key = "fixture-never-send"
    api_settings.llm_available_models = "model-a"
    api_settings.llm_model = "model-a"
    api_settings.qwen_models = api_settings.kimi_models = api_settings.glm_models = ""


def unavailable(*args: Any, **kwargs: Any) -> None:
    raise AssertionError("product workflows must not access a research catalog")


def test_default_edition_and_product_distribution_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTIC_EDITION", raising=False)
    assert Settings(_env_file=None).agentic_edition == DEFAULT_EDITION
    monkeypatch.setattr("app.core.config.RESEARCH_AVAILABLE", False)
    with pytest.raises(ValueError, match="产品版不包含研究模块"):
        Settings(_env_file=None, agentic_edition="research")


async def test_product_management_never_loads_registry(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.agent_profile.load_evaluation_catalog", unavailable)
    options = (await api_client.get("/api/agent-profiles/options")).json()["data"]
    assert options["edition"] == "product" and options["evaluation_profiles"] == []
    original = await profile(api_client)
    root = f"/api/agent-profiles/{original['id']}"
    config = deepcopy(original["current_revision"]["config"])
    config["system_prompt"] = "产品配置修改"
    updated = await api_client.patch(root, json={"expected_row_version": 1, "config": config})
    assert updated.status_code == 200
    assert (await api_client.post(root + "/copy", json={"name": "产品副本"})).status_code == 201
    restored = await api_client.post(
        root + "/restore",
        json={
            "expected_row_version": 2,
            "revision_id": original["current_revision"]["id"],
        },
    )
    assert restored.status_code == 200
    assert (await api_client.delete(root, params={"expected_row_version": 3})).status_code == 200


async def test_product_rejects_new_research_refs_without_reading_registry(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.agent_profile.load_evaluation_catalog", unavailable)
    reference = {
        "profile_id": "synthetic",
        "registry_version": "1",
        "registry_sha256": "a" * 64,
        "usage": "offline",
    }
    original = await profile(api_client)
    config = deepcopy(original["current_revision"]["config"])
    config["evaluation_profiles"] = [reference]
    created = await api_client.post(
        "/api/agent-profiles", json={"name": "研究引用", "config": config}
    )
    assert created.status_code == 400
    edited = await api_client.patch(
        f"/api/agent-profiles/{original['id']}", json={"expected_row_version": 1, "config": config}
    )
    assert edited.status_code == 400


async def test_research_history_remains_usable_after_switching_to_product(
    api_client: AsyncClient,
    api_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.generation import get_chat_completion_gateway
    from app.main import app
    from tests.test_agent_profiles_api import evaluation_reference

    api_settings.agentic_edition = "research"
    original = await profile(api_client, evaluation_profiles=[evaluation_reference()])
    conv = await quick(api_client, original["id"])
    root = f"/api/agent-profiles/{original['id']}"
    api_settings.agentic_edition = "product"
    monkeypatch.setattr("app.services.agent_profile.load_evaluation_catalog", unavailable)
    monkeypatch.setattr("app.agents.validation.load_evaluation_catalog", unavailable)
    assert (await api_client.get(root)).json()["data"]["current_revision"] == original[
        "current_revision"
    ]
    config = deepcopy(original["current_revision"]["config"])
    config["system_prompt"] = "仍可编辑"
    assert (
        await api_client.patch(root, json={"expected_row_version": 1, "config": config})
    ).status_code == 200
    for version, enabled in ((2, False), (3, True)):
        assert (
            await api_client.patch(root, json={"expected_row_version": version, "enabled": enabled})
        ).status_code == 200
    restored = await api_client.post(
        root + "/restore",
        json={
            "expected_row_version": 4,
            "revision_id": original["current_revision"]["id"],
        },
    )
    assert restored.status_code == 200
    copied = (await api_client.post(root + "/copy", json={"name": "不带研究引用的副本"})).json()[
        "data"
    ]
    assert copied["current_revision"]["config"]["evaluation_profiles"] == []
    gateway = RecordingGateway()
    app.dependency_overrides[get_chat_completion_gateway] = lambda: gateway
    response = await api_client.post(
        f"/api/quick-conversations/{conv['id']}/messages/stream",
        json={"message": "继续对话", "web_search": False},
    )
    assert _sse_event_data(response.text, "complete")["agent_runtime"]["revision_number"] == 1
    assert (await api_client.get(root + "/revisions/" + original["current_revision"]["id"])).json()[
        "data"
    ] == original["current_revision"]
    assert len(gateway.calls) == 1


@pytest.mark.parametrize("edition", ["product", "research"])
def test_source_archives_exclude_runtime_data_and_set_capabilities(
    tmp_path: Path, edition: str
) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "edition_builder", root / "scripts/build_editions.py"
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    archive = builder.build(root, tmp_path, edition, "test")
    with ZipFile(archive) as bundle:
        names = bundle.namelist()
        manifest = json.loads(bundle.read("edition-manifest.json"))
        assert manifest["edition"] == edition
        assert f"AGENTIC_EDITION={edition}".encode() in bundle.read(".env.example")
        assert not any(name.startswith(("data/", "tmp/", "output/")) for name in names)
        assert not any(Path(name).suffix in builder.FORBIDDEN_SUFFIXES for name in names)
        assert ".env" not in names and "backend/.env" not in names
        assert "backend/migrations/versions/20260910_06_soft_delete_agent_profiles.py" in names
        assert ("backend/app/evaluation/registry.json" in names) is (edition == "research")
        assert ("backend/scripts/manage_benchmarks.py" in names) is (edition == "research")
        if edition == "product":
            assert not any(name.startswith("benchmarks/") for name in names)
            assert b"RESEARCH_AVAILABLE = False" in bundle.read("backend/app/core/distribution.py")
        import hashlib

        for name, expected in manifest["files"].items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == expected
