from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.agents.configuration import AgentConfiguration
from app.agents.validation import load_evaluation_catalog, request_web_search_enabled
from app.core.config import Settings
from app.core.exceptions import ConflictError, InvalidInputError
from app.repositories.agent_profile import AgentProfileRepository
from app.services.agent_profile import AgentProfileService

ROOT = "/api/agent-profiles"
MODEL = {"provider": "deepseek", "model": "fixture-agent-model"}


@pytest.fixture(autouse=True)
def configured_provider(api_settings: Settings) -> None:
    api_settings.agentic_edition = "research"
    api_settings.llm_api_key = "fixture-key-never-send"
    api_settings.llm_available_models = MODEL["model"]
    api_settings.llm_model = MODEL["model"]
    api_settings.qwen_models = "fixture-qwen"
    api_settings.qwen_api_key = ""
    api_settings.kimi_models = ""
    api_settings.glm_models = ""


async def create(client: AsyncClient, name: str = "A", **config: Any) -> dict[str, Any]:
    response = await client.post(ROOT, json={"name": name, "config": {"model": MODEL, **config}})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def evaluation_reference(profile_id: str = "ragtruth-nli-span-localization") -> dict[str, str]:
    catalog = load_evaluation_catalog()
    return {
        "profile_id": profile_id,
        "registry_version": catalog.registry.release_version,
        "registry_sha256": catalog.sha256,
        "usage": "offline",
    }


async def test_management_lifecycle_and_immutable_revisions(api_client: AsyncClient) -> None:
    original = await create(api_client, "  A  ")
    assert original["name"] == "A"
    assert original["row_version"] == 1
    r1 = original["current_revision"]
    path = f"{ROOT}/{original['id']}"
    cfg = deepcopy(r1["config"])
    cfg["system_prompt"] = "新的合成配置"
    result = await api_client.patch(
        path,
        json={
            "expected_row_version": 1,
            "config": cfg,
            "change_summary": "r2",
        },
    )
    assert result.status_code == 200, result.text
    current = result.json()["data"]
    assert current["row_version"] == 2
    assert current["current_revision"]["revision_number"] == 2
    assert current["current_revision"]["config_sha256"] != r1["config_sha256"]
    old = (await api_client.get(f"{path}/revisions/{r1['id']}")).json()["data"]
    assert old == r1
    restored = (
        await api_client.post(
            f"{path}/restore",
            json={
                "expected_row_version": 2,
                "revision_id": r1["id"],
            },
        )
    ).json()["data"]
    assert restored["row_version"] == 3
    assert restored["current_revision"]["revision_number"] == 3
    assert restored["current_revision"]["id"] != r1["id"]
    assert restored["current_revision"]["config_sha256"] == r1["config_sha256"]
    versions = (await api_client.get(f"{path}/revisions")).json()["data"]
    assert [v["revision_number"] for v in versions] == [3, 2, 1]
    assert len((await api_client.get(f"{path}/revisions?limit=1&offset=1")).json()["data"]) == 1

    copied_response = await api_client.post(
        f"{path}/copy",
        json={
            "name": "B",
            "revision_id": r1["id"],
            "description": "独立副本",
        },
    )
    assert copied_response.status_code == 201
    copied = copied_response.json()["data"]
    assert copied["id"] != original["id"]
    assert copied["current_revision"]["id"] != r1["id"]
    assert copied["current_revision"]["revision_number"] == 1
    assert copied["current_revision"]["config_sha256"] == r1["config_sha256"]

    disabled = (
        await api_client.patch(
            path,
            json={
                "expected_row_version": 3,
                "enabled": False,
                "description": "停用说明",
            },
        )
    ).json()["data"]
    assert disabled["enabled"] is False
    assert disabled["current_revision"]["id"] == restored["current_revision"]["id"]
    assert len((await api_client.get(ROOT + "?enabled=false")).json()["data"]) == 1
    enabled = (
        await api_client.patch(
            path,
            json={
                "expected_row_version": 4,
                "enabled": True,
                "description": None,
            },
        )
    ).json()["data"]
    assert enabled["enabled"] and enabled["description"] is None
    assert enabled["row_version"] == 5
    assert len((await api_client.get(ROOT + "?limit=1&offset=1")).json()["data"]) == 1
    assert (await api_client.delete(path)).status_code == 422  # Explicit version required.
    assert (await api_client.get(path)).status_code == 200
    for payload in (original, current, restored, copied, enabled):
        assert "fixture-key-never-send" not in str(payload)
        assert "api_key" not in str(payload)


@pytest.mark.parametrize(
    "patch",
    [
        {"config": None},
        {"name": None},
        {"enabled": None},
        {"name": "   "},
        {},
        {"description": "x", "change_summary": "ignored?"},
        {"enabled": "true"},
        {"row_version": 1},
        {"expected_row_version": True, "enabled": False},
    ],
)
async def test_invalid_patch_rejected_without_writes(
    api_client: AsyncClient, patch: dict[str, Any]
) -> None:
    profile = await create(api_client)
    response = await api_client.patch(
        f"{ROOT}/{profile['id']}",
        json={
            "expected_row_version": 1,
            **patch,
        },
    )
    assert response.status_code == 422
    assert (await api_client.get(f"{ROOT}/{profile['id']}")).json()["data"] == profile


@pytest.mark.parametrize(
    "config,code",
    [
        ({"model": {"provider": "unknown", "model": "fixture-agent-model"}}, 400),
        ({"model": {"provider": "deepseek", "model": "not-allowed"}}, 400),
        ({"model": {"provider": "qwen", "model": "fixture-qwen"}}, 503),
        ({"allowed_course_ids": [str(uuid4())]}, 400),
        ({"tools": {"shell": True}}, 422),
        ({"api_key": "do-not-echo"}, 422),
        ({"retrieval": {"answer_top_k": 10, "answer_candidate_k": 5}}, 422),
        ({"context": {"rag_max_chars": 999999}}, 422),
    ],
)
async def test_invalid_create_leaves_no_identity_or_config(
    api_client: AsyncClient, config: dict[str, Any], code: int
) -> None:
    response = await api_client.post(
        ROOT,
        json={
            "name": "invalid",
            "config": {"model": MODEL, **config},
        },
    )
    assert response.status_code == code
    assert "do-not-echo" not in response.text
    assert (await api_client.get(ROOT)).json()["data"] == []


async def test_rejects_ambiguous_model_routing(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    api_settings.qwen_models = MODEL["model"]
    api_settings.qwen_api_key = "fixture-qwen-key"
    response = await api_client.post(ROOT, json={"name": "x", "config": {"model": MODEL}})
    assert response.status_code == 400


async def test_options_and_evaluation_usage_enforcement(api_client: AsyncClient) -> None:
    response = await api_client.get(ROOT + "/options")
    assert response.status_code == 200
    assert "fixture-key-never-send" not in response.text
    assert "api_key" not in response.text and "base_url" not in response.text
    options = response.json()["data"]
    by_id = {p["profile_id"]: p for p in options["evaluation_profiles"]}
    assert len(by_id) == 4
    assert by_id["fiqa-dense-retrieval"]["allowed_usages"] == ["offline"]
    assert by_id["ragtruth-nli-span-localization"]["allowed_usages"] == ["offline", "advisory"]
    ref = evaluation_reference()
    ref["usage"] = "advisory"
    await create(api_client, evaluation_profiles=[ref])
    for change, code in [
        ({"profile_id": "w6-d2-dense-direct-rerank"}, 400),
        ({"profile_id": "w6-d3-two-stage-completeness"}, 400),
        ({"profile_id": "fiqa-dense-retrieval"}, 400),
        ({"registry_version": "999.0.0"}, 400),
        ({"registry_sha256": "0" * 64}, 400),
        ({"usage": "production"}, 422),
    ]:
        bad = {**ref, **change}
        result = await api_client.post(
            ROOT,
            json={
                "name": "invalid",
                "config": {"model": MODEL, "evaluation_profiles": [bad]},
            },
        )
        assert result.status_code == code, result.text
    assert len((await api_client.get(ROOT)).json()["data"]) == 1


async def test_history_survives_dependency_loss_but_new_use_is_rejected(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    course_id = (await api_client.post("/api/courses", json={"name": "space"})).json()["data"]["id"]
    original = await create(api_client, allowed_course_ids=[course_id])
    path = f"{ROOT}/{original['id']}"
    assert (await api_client.delete(f"/api/courses/{course_id}")).status_code == 200
    assert (await api_client.get(path)).json()["data"] == original
    assert (await api_client.get(path + "/revisions")).status_code == 200
    assert (await api_client.post(path + "/copy", json={"name": "copy"})).status_code == 400
    assert (
        await api_client.post(
            path + "/restore",
            json={
                "expected_row_version": 1,
                "revision_id": original["current_revision"]["id"],
            },
        )
    ).status_code == 400
    disabled = (
        await api_client.patch(
            path,
            json={
                "expected_row_version": 1,
                "enabled": False,
            },
        )
    ).json()["data"]
    assert disabled["enabled"] is False
    assert (
        await api_client.patch(
            path,
            json={
                "expected_row_version": 2,
                "enabled": True,
            },
        )
    ).status_code == 400
    api_settings.llm_api_key = ""
    assert (await api_client.get(path)).status_code == 200
    assert (
        await api_client.patch(
            path,
            json={
                "expected_row_version": 2,
                "name": "renamed",
            },
        )
    ).status_code == 200
    # Repair configuration while keeping the disabled identity disabled.
    api_settings.llm_api_key = "fixture-key"
    repaired = (
        await api_client.patch(
            path,
            json={
                "expected_row_version": 3,
                "config": {"model": MODEL},
            },
        )
    ).json()["data"]
    assert repaired["enabled"] is False and repaired["current_revision"]["revision_number"] == 2


async def test_stale_edits_name_collision_and_cross_agent_revision(
    api_client: AsyncClient,
) -> None:
    a, b = await create(api_client, "A"), await create(api_client, "B")
    path = f"{ROOT}/{a['id']}"
    assert (
        await api_client.patch(
            path,
            json={
                "expected_row_version": 99,
                "enabled": False,
            },
        )
    ).status_code == 409
    assert (
        await api_client.patch(
            path,
            json={
                "expected_row_version": 1,
                "name": "B",
                "config": {"model": MODEL},
            },
        )
    ).status_code == 409
    for action, payload in (
        ("restore", {"expected_row_version": 1, "revision_id": b["current_revision"]["id"]}),
        ("copy", {"name": "C", "revision_id": b["current_revision"]["id"]}),
    ):
        assert (await api_client.post(path + "/" + action, json=payload)).status_code == 404
    assert (
        await api_client.get(path + "/revisions/" + b["current_revision"]["id"])
    ).status_code == 404
    assert (await api_client.get(path)).json()["data"] == a
    assert len((await api_client.get(path + "/revisions")).json()["data"]) == 1
    assert (await api_client.get(ROOT + "?limit=101")).status_code == 422
    assert (await api_client.get(f"{ROOT}/{uuid4()}")).status_code == 404


async def test_concurrent_edits_have_exactly_one_winner(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = await create(api_client)
    path = f"{ROOT}/{profile['id']}"
    original = AgentProfileService.validate_configuration
    ready = asyncio.Event()
    arrivals = 0

    async def synchronized(self: AgentProfileService, config: AgentConfiguration) -> None:
        nonlocal arrivals
        await original(self, config)
        arrivals += 1
        if arrivals == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=5)

    monkeypatch.setattr(AgentProfileService, "validate_configuration", synchronized)
    responses = await asyncio.wait_for(
        asyncio.gather(
            *(
                api_client.patch(
                    path,
                    json={
                        "expected_row_version": 1,
                        "config": {"model": MODEL, "system_prompt": prompt},
                    },
                )
                for prompt in ("editor one", "editor two")
            )
        ),
        timeout=15,
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    current = (await api_client.get(path)).json()["data"]
    assert current["row_version"] == 2
    assert current["current_revision"]["revision_number"] == 2
    assert len((await api_client.get(path + "/revisions")).json()["data"]) == 2


async def test_append_failure_rolls_back_identity_and_revision(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = await create(api_client)
    path = f"{ROOT}/{profile['id']}"

    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected append failure")

    monkeypatch.setattr(AgentProfileRepository, "append", fail)
    with pytest.raises(RuntimeError, match="injected append"):
        await api_client.patch(
            path,
            json={
                "expected_row_version": 1,
                "name": "not committed",
                "config": {"model": MODEL},
            },
        )
    assert (await api_client.get(path)).json()["data"] == profile
    with pytest.raises(RuntimeError, match="injected append"):
        await api_client.post(ROOT, json={"name": "incomplete", "config": {"model": MODEL}})
    assert len((await api_client.get(ROOT)).json()["data"]) == 1


async def test_registry_unavailable_does_not_hide_history(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = await create(api_client, evaluation_profiles=[evaluation_reference()])

    def fail() -> None:
        raise ConflictError("评测配置注册表不可用。")

    monkeypatch.setattr("app.services.agent_profile.load_evaluation_catalog", fail)
    assert (await api_client.get(ROOT + "/options")).status_code == 409
    assert (await api_client.get(f"{ROOT}/{profile['id']}")).status_code == 200
    assert (
        await api_client.post(f"{ROOT}/{profile['id']}/copy", json={"name": "copy"})
    ).status_code == 409
    await create(api_client, "no evaluation")


def test_request_permissions_only_narrow(api_settings: Settings) -> None:
    space = uuid4()
    config = AgentConfiguration.model_validate({"model": MODEL, "allowed_course_ids": [space]})
    assert request_web_search_enabled(config, api_settings, course_id=space)
    for options in ({"requested": False}, {"course_only": True}, {"task_type": "summary"}):
        assert not request_web_search_enabled(config, api_settings, course_id=space, **options)
    api_settings.external_search_enabled = False
    assert not request_web_search_enabled(config, api_settings, course_id=space)
    api_settings.external_search_enabled = True
    disabled = AgentConfiguration.model_validate({"model": MODEL, "tools": {"web_search": False}})
    assert not request_web_search_enabled(disabled, api_settings, course_id=None)
    with pytest.raises(InvalidInputError):
        request_web_search_enabled(config, api_settings, course_id=uuid4())
    with pytest.raises(InvalidInputError):
        request_web_search_enabled(config, api_settings, course_id=space, model="other")
