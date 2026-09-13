from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import InvalidInputError
from app.db.session import create_database_engine
from app.training.schemas import DatasetManifest
from app.training.service import DatasetService
from app.training.storage import DatasetStorage
from app.training.validation import MAX_BYTES, canonical, validate_jsonl
from tests.test_agent_runtime import profile

ROOT = "/api/training-datasets"
MANIFEST: dict[str, Any] = {
    "schema_version": 1,
    "target": "reranker",
    "source": "本地合成验收数据",
    "license_id": "synthetic-owned",
    "license_notes": "仅用于自动测试，无第三方材料。",
    "training_allowed": True,
    "pii_status": "clean",
    "pii_notes": "合成文本，已人工复核。",
    "source_course_ids": [],
}


def rows() -> list[dict[str, Any]]:
    return [
        {
            "id": "a",
            "source_id": "fruit",
            "group_id": "fruit",
            "split": "train",
            "query": "苹果是什么颜色",
            "document": "成熟苹果具有红色果皮和可食用果肉。",
            "relevance": 1,
        },
        {
            "id": "b",
            "source_id": "planet",
            "group_id": "planet",
            "split": "validation",
            "query": "行星如何公转",
            "document": "引力使天体沿着椭圆轨道围绕恒星运动。",
            "relevance": 0,
        },
    ]


def jsonl(samples: list[dict[str, Any]] | None = None) -> bytes:
    return (
        b"\n".join(canonical(row) for row in (samples if samples is not None else rows())) + b"\n"
    )


@pytest.fixture(autouse=True)
def isolated(api_settings: Settings, tmp_path: Path) -> None:
    api_settings.agentic_edition = "research"
    api_settings.training_data_dir = tmp_path / "training"
    api_settings.llm_api_key = "fixture-never-send"
    api_settings.llm_model = "model-a"
    api_settings.llm_available_models = "model-a"


async def new_dataset(client: AsyncClient, name: str = "合成数据") -> dict[str, Any]:
    response = await client.post(ROOT, json={"name": name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def upload(
    client: AsyncClient,
    dataset_id: str,
    version: int = 1,
    manifest: dict[str, Any] | None = None,
    data: bytes | None = None,
    filename: str = "samples.jsonl",
) -> Any:
    return await client.post(
        f"{ROOT}/{dataset_id}/revisions",
        data={"manifest": json.dumps(manifest or MANIFEST), "expected_row_version": str(version)},
        files={
            "file": (filename, data if data is not None else jsonl(), "application/octet-stream")
        },
    )


async def revision(client: AsyncClient, **kwargs: Any) -> tuple[str, str]:
    dataset = await new_dataset(client)
    result = await upload(client, dataset["id"], **kwargs)
    assert result.status_code == 201, result.text
    return dataset["id"], result.json()["data"]["id"]


async def review(client: AsyncClient, did: str, rid: str, version: int, status: str) -> Any:
    return await client.post(
        f"{ROOT}/{did}/revisions/{rid}/reviews",
        json={
            "expected_row_version": version,
            "status": status,
            "reviewer": "合成复核人",
            "note": "仅复核合成样本，确认当前来源、许可及隐私处理。",
        },
    )


async def approved(client: AsyncClient, **kwargs: Any) -> tuple[str, str]:
    did, rid = await revision(client, **kwargs)
    assert (await review(client, did, rid, 2, "pending_review")).status_code == 200
    result = await review(client, did, rid, 3, "approved")
    assert result.status_code == 200, result.text
    return did, rid


async def eligible(client: AsyncClient, did: str, rid: str, pid: str) -> dict[str, Any]:
    result = await client.get(
        f"{ROOT}/{did}/revisions/{rid}/eligibility", params={"agent_profile_id": pid}
    )
    assert result.status_code == 200, result.text
    return dict(result.json()["data"])


@pytest.mark.parametrize("target", ["scorer", "reranker"])
def test_valid_contract_hashes_and_reproducible_report(target: str) -> None:
    samples = rows()
    if target == "scorer":
        for row in samples:
            row["response"] = row.pop("document")
            row["evidence"] = ["证据来自独立合成材料：" + row["source_id"]]
            row["score"] = row.pop("relevance") / 2
    data = jsonl(samples)
    manifest = DatasetManifest.model_validate({**MANIFEST, "target": target})
    report = validate_jsonl(data, manifest)
    assert report.valid and report.approvable and report.sample_count == 2
    assert report == validate_jsonl(data, manifest)
    assert report.splits["train"].count == report.splits["validation"].count == 1
    assert report.splits["train"].sha256 != report.splits["validation"].sha256


@pytest.mark.parametrize(
    "change,code",
    [
        ({"split": "test"}, "SPLIT_NOT_ALLOWED"),
        ({"split": "sealed_test"}, "SPLIT_NOT_ALLOWED"),
        ({"split": "dev"}, "SPLIT_NOT_ALLOWED"),
        ({"relevance": True}, "INVALID_SAMPLE_SCHEMA"),
        ({"relevance": 2}, "INVALID_SAMPLE_SCHEMA"),
        ({"relevance": "1"}, "INVALID_SAMPLE_SCHEMA"),
        ({"unknown": "private"}, "INVALID_SAMPLE_SCHEMA"),
        ({"document": ""}, "INVALID_SAMPLE_SCHEMA"),
        ({"source_id": ""}, "INVALID_SAMPLE_SCHEMA"),
    ],
)
def test_bad_sample_shapes_are_safe(change: dict[str, Any], code: str) -> None:
    samples = rows()
    samples[0].update(change)
    report = validate_jsonl(jsonl(samples), DatasetManifest.model_validate(MANIFEST))
    assert not report.valid and not report.approvable
    assert any(issue.code == code and issue.line == 1 for issue in report.issues)
    assert "private" not in report.model_dump_json()


@pytest.mark.parametrize(
    "manifest,code",
    [
        ({"license_id": "unknown"}, "LICENSE_NOT_CLEARED"),
        ({"training_allowed": False}, "LICENSE_NOT_CLEARED"),
        ({"pii_status": "pending"}, "PII_REVIEW_PENDING"),
    ],
)
async def test_unreviewable_metadata_never_approved(
    api_client: AsyncClient,
    manifest: dict[str, Any],
    code: str,
) -> None:
    did, rid = await revision(api_client, manifest={**MANIFEST, **manifest})
    snapshot = (await api_client.get(f"{ROOT}/{did}/revisions/{rid}")).json()["data"]
    assert code in [i["code"] for i in snapshot["report"]["issues"]]
    assert (await review(api_client, did, rid, 2, "pending_review")).status_code == 200
    assert (await review(api_client, did, rid, 3, "approved")).status_code == 400
    assert (await api_client.get(f"{ROOT}/{did}")).json()["data"]["row_version"] == 3


@pytest.mark.parametrize("kind", ["source", "group", "exact", "near", "pii"])
def test_contamination_and_sensitive_content_block_approval(kind: str) -> None:
    samples = rows()
    if kind in {"source", "group"}:
        samples[1][kind + "_id"] = samples[0][kind + "_id"].upper() + "!"
    elif kind in {"exact", "near"}:
        samples[1]["query"] = samples[0]["query"]
        samples[1]["document"] = samples[0]["document"] + ("多" if kind == "near" else "!!!")
    else:
        samples[0]["document"] = "联系合成测试邮箱 synthetic@example.com"
    report = validate_jsonl(jsonl(samples), DatasetManifest.model_validate(MANIFEST))
    assert report.valid and not report.approvable
    assert "synthetic@example.com" not in report.model_dump_json()


@pytest.mark.parametrize(
    "data", [b"\xff", b"{}\n", b"\n", b"[]\n", b'{"split":"train","split":"test"}\n']
)
def test_malformed_upload(data: bytes) -> None:
    report = validate_jsonl(data, DatasetManifest.model_validate(MANIFEST))
    assert not report.valid


async def test_validation_does_not_persist_and_import_ignores_filename(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    response = await api_client.post(
        ROOT + "/validate",
        data={"manifest": json.dumps(MANIFEST)},
        files={"file": ("../../escape.jsonl", jsonl())},
    )
    assert response.status_code == 200 and response.json()["data"]["approvable"]
    assert not api_settings.training_data_dir.exists()
    did, rid = await revision(api_client, filename="C:\\private\\escape.jsonl")
    assert list(api_settings.training_data_dir.iterdir()) == [
        api_settings.training_data_dir / (UUID(rid).hex + ".jsonl")
    ]
    assert "escape" not in (await api_client.get(f"{ROOT}/{did}/revisions/{rid}")).text


async def test_approval_revoke_and_service_gate(
    api_client: AsyncClient, api_settings: Settings
) -> None:
    agent = await profile(api_client)
    did, rid = await approved(api_client)
    assert (await eligible(api_client, did, rid, agent["id"]))["eligible"]
    assert (await review(api_client, did, rid, 4, "revoked")).status_code == 200
    assert not (await eligible(api_client, did, rid, agent["id"]))["eligible"]
    engine = create_database_engine(api_settings.database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            with pytest.raises(InvalidInputError, match="DATASET_NOT_APPROVED"):
                await DatasetService(session, api_settings).require_eligible(
                    UUID(did), UUID(rid), UUID(agent["id"])
                )
    finally:
        await engine.dispose()
    events = (await api_client.get(f"{ROOT}/{did}/revisions/{rid}/reviews")).json()["data"]
    assert [e["status"] for e in events] == ["draft", "pending_review", "approved", "revoked"]


async def test_review_conflict_and_invalid_transition(api_client: AsyncClient) -> None:
    did, rid = await revision(api_client)
    assert (await review(api_client, did, rid, 2, "approved")).status_code == 409
    results = await asyncio.gather(
        *(review(api_client, did, rid, 2, "pending_review") for _ in range(2))
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    events = (await api_client.get(f"{ROOT}/{did}/revisions/{rid}/reviews")).json()["data"]
    assert len(events) == 2


async def test_metadata_changes_new_revision_needs_new_review(api_client: AsyncClient) -> None:
    did, rid = await approved(api_client)
    before = (await api_client.get(f"{ROOT}/{did}/revisions/{rid}")).json()["data"]
    result = await upload(api_client, did, 4, {**MANIFEST, "source": "新的合成来源声明"})
    assert result.status_code == 201
    assert result.json()["data"]["status"] == "draft"
    assert result.json()["data"]["revision_number"] == 2
    assert (await api_client.get(f"{ROOT}/{did}/revisions/{rid}")).json()["data"] == before
    assert (await upload(api_client, did, 4)).status_code == 409


@pytest.mark.parametrize(
    "mode",
    ["tamper", "missing", "source_deleted", "agent_disabled", "agent_deleted", "space_removed"],
)
async def test_runtime_gate_rechecks_current_state(
    api_client: AsyncClient,
    api_settings: Settings,
    mode: str,
) -> None:
    course = (await api_client.post("/api/courses", json={"name": "合成来源空间"})).json()["data"]
    agent = await profile(api_client, allowed_course_ids=[course["id"]])
    did, rid = await approved(
        api_client, manifest={**MANIFEST, "source_course_ids": [course["id"]]}
    )
    assert (await eligible(api_client, did, rid, agent["id"]))["eligible"]
    path = api_settings.training_data_dir / (UUID(rid).hex + ".jsonl")
    if mode == "tamper":
        path.write_bytes(jsonl() + b" ")
    elif mode == "missing":
        path.unlink()
    elif mode == "source_deleted":
        assert (await api_client.delete(f"/api/courses/{course['id']}")).status_code == 200
    elif mode == "agent_deleted":
        assert (
            await api_client.delete(
                f"/api/agent-profiles/{agent['id']}", params={"expected_row_version": 1}
            )
        ).status_code == 200
    else:
        payload: dict[str, Any] = {"expected_row_version": 1}
        if mode == "agent_disabled":
            payload["enabled"] = False
        else:
            config = deepcopy(agent["current_revision"]["config"])
            config["allowed_course_ids"] = []
            payload["config"] = config
        assert (
            await api_client.patch(f"/api/agent-profiles/{agent['id']}", json=payload)
        ).status_code == 200
    result = await eligible(api_client, did, rid, agent["id"])
    assert not result["eligible"] and result["reasons"]


async def test_wrong_owner_and_unknown_agent_rejected(api_client: AsyncClient) -> None:
    did, rid = await approved(api_client)
    other = await new_dataset(api_client, "另一身份")
    assert (await api_client.get(f"{ROOT}/{other['id']}/revisions/{rid}")).status_code == 404
    assert not (await eligible(api_client, did, rid, str(uuid4())))["eligible"]
    assert (await api_client.get(ROOT, params={"limit": 101})).status_code == 422


async def test_sealed_split_and_oversize_cannot_enter_registry(api_client: AsyncClient) -> None:
    dataset = await new_dataset(api_client)
    samples = rows()
    samples[1]["split"] = "test"
    assert (await upload(api_client, dataset["id"], data=jsonl(samples))).status_code == 400
    assert (await upload(api_client, dataset["id"], data=b"x" * (MAX_BYTES + 1))).status_code == 413
    assert (await api_client.get(f"{ROOT}/{dataset['id']}/revisions")).json()["data"] == []


async def test_product_blocks_every_training_route(
    api_client: AsyncClient, api_settings: Settings
) -> None:
    did, rid = await approved(api_client)
    api_settings.agentic_edition = "product"
    path = f"{ROOT}/{did}/revisions/{rid}"
    for url in (
        ROOT,
        f"{ROOT}/{did}",
        f"{ROOT}/{did}/revisions",
        path,
        path + "/reviews",
        path + "/eligibility?agent_profile_id=" + str(uuid4()),
    ):
        assert (await api_client.get(url)).status_code == 403
    assert (await api_client.post(ROOT, json={"name": "denied"})).status_code == 403
    assert (await upload(api_client, did, 4)).status_code == 403
    assert (await review(api_client, did, rid, 4, "revoked")).status_code == 403
    assert (
        await api_client.post(
            ROOT + "/validate",
            data={"manifest": json.dumps(MANIFEST)},
            files={"file": ("data.jsonl", jsonl())},
        )
    ).status_code == 403
    assert (await api_client.get("/api/agent-profiles/options")).status_code == 200


async def test_file_write_failure_rolls_back_database(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = await new_dataset(api_client)

    def fail(*args: Any) -> None:
        raise InvalidInputError("合成磁盘错误")

    monkeypatch.setattr(DatasetStorage, "write", fail)
    assert (await upload(api_client, dataset["id"])).status_code == 400
    assert (await api_client.get(f"{ROOT}/{dataset['id']}")).json()["data"]["row_version"] == 1
    assert (await api_client.get(f"{ROOT}/{dataset['id']}/revisions")).json()["data"] == []


async def test_frozen_records_protected_against_sql_and_replace(
    api_client: AsyncClient,
    api_settings: Settings,
) -> None:
    await approved(api_client)
    path = api_settings.database_url.removeprefix("sqlite+aiosqlite:///")
    with sqlite3.connect(path) as connection:
        for table in ("training_dataset_revisions", "training_dataset_reviews"):
            for query in (
                f"UPDATE {table} SET id=id",
                f"DELETE FROM {table}",
                f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}",
            ):
                with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                    connection.execute(query)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_storage_rejects_linked_parent_without_reading_target(tmp_path: Path) -> None:
    # Windows junction is covered with mocked lstat reparse attributes without OS privilege.
    import stat
    from types import SimpleNamespace
    from unittest.mock import patch

    root = tmp_path / "linked"
    original = Path.lstat

    def linked(path: Path) -> Any:
        if path == root:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
        return original(path)

    with patch.object(Path, "lstat", linked), pytest.raises(InvalidInputError, match="重解析点"):
        DatasetStorage(root).read(uuid4())


def test_escaped_pii_and_unicode_are_not_validation_bypasses() -> None:
    samples = rows()
    samples[0]["document"] = "合成测试 synthetic@example.com"
    encoded = jsonl(samples).replace(b"@", b"\\u0040")
    report = validate_jsonl(encoded, DatasetManifest.model_validate(MANIFEST))
    assert not report.approvable and any(i.code == "SENSITIVE_PATTERN" for i in report.issues)
    invalid = jsonl().replace("苹果".encode(), b"\\ud800")
    assert not validate_jsonl(invalid, DatasetManifest.model_validate(MANIFEST)).valid


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": "1"},
        {"schema_version": 2},
        {"training_allowed": "true"},
        {"extra": "test"},
        {"source_course_ids": ["invalid"]},
    ],
)
async def test_invalid_manifest_has_sanitized_error(
    api_client: AsyncClient,
    change: dict[str, Any],
) -> None:
    result = await api_client.post(
        ROOT + "/validate",
        data={"manifest": json.dumps({**MANIFEST, **change})},
        files={"file": ("data.jsonl", jsonl())},
    )
    assert result.status_code == 400
    assert result.json()["error"]["message"] == "manifest 格式或字段不合法。"


async def test_duplicate_import_concurrency_only_one_revision(api_client: AsyncClient) -> None:
    dataset = await new_dataset(api_client)
    results = await asyncio.gather(
        upload(api_client, dataset["id"]), upload(api_client, dataset["id"])
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    revisions = (await api_client.get(f"{ROOT}/{dataset['id']}/revisions")).json()["data"]
    assert len(revisions) == 1


def test_storage_rejects_hardlinked_file(tmp_path: Path) -> None:
    import os

    store = DatasetStorage(tmp_path)
    source = tmp_path / "source.jsonl"
    source.write_bytes(jsonl())
    rid = uuid4()
    os.link(source, store.path(rid))
    with pytest.raises(InvalidInputError, match="链接状态"):
        store.read(rid)


def test_validation_work_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.training.validation as validation

    manifest = DatasetManifest.model_validate(MANIFEST)
    monkeypatch.setattr(validation, "MAX_ROWS", 1)
    assert not validate_jsonl(jsonl(), manifest).valid
    monkeypatch.setattr(validation, "MAX_ROWS", 5000)
    monkeypatch.setattr(validation, "MAX_SHINGLES", 1)
    assert any(i.code == "DEDUP_WORK_LIMIT" for i in validate_jsonl(jsonl(), manifest).issues)


async def test_entire_multipart_request_is_bounded(api_client: AsyncClient) -> None:
    result = await api_client.post(
        ROOT + "/validate",
        data={"manifest": json.dumps(MANIFEST)},
        files={"file": ("oversize.jsonl", b"x" * (MAX_BYTES + 65537))},
    )
    assert result.status_code == 413
    assert result.json()["error"]["code"] == "FILE_TOO_LARGE"
