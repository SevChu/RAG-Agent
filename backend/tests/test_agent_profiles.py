from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.configuration import AgentConfiguration
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.models import AgentProfile, AgentProfileRevision, Conversation, ConversationKind

MODEL = {"provider": "deepseek", "model": "fixture-model"}


def make_config(**changes: Any) -> AgentConfiguration:
    return AgentConfiguration.model_validate({"model": MODEL, **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"api_key": "fixture-secret"},
        {"model": {**MODEL, "api_key": "fixture-secret"}},
        {"model": {**MODEL, "model": " "}},
        {"schema_version": 2},
        {"tools": {"shell": True}},
        {"tools": {"web_search": "true"}},
        {"context": {"rag_max_messages": 21}},
        {"context": {"rag_max_messages": True}},
        {"context": {"quick_max_chars": 40001}},
        {"context": {"strategy": "long-term-memory"}},
        {"retrieval": {"answer_top_k": 10, "answer_candidate_k": 5}},
        {"retrieval": {"summary_top_k": 12, "summary_candidate_k": 10}},
        {"retrieval": {"exam_top_k": 12, "exam_candidate_k": 10}},
        {"retrieval": {"min_similarity_score": float("nan")}},
        {"retrieval": {"strategy": "fiqa-dense-retrieval"}},
        {
            "evaluation_profiles": [
                {
                    "profile_id": "fixture",
                    "registry_version": "1.1.0",
                    "registry_sha256": "a" * 64,
                    "usage": "production",
                }
            ]
        },
    ],
)
def test_configuration_rejects_unsafe_or_unsupported_shapes(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_config(**changes)


def test_configuration_canonical_hash_and_nested_immutability() -> None:
    a, b = uuid4(), uuid4()
    first = make_config(allowed_course_ids=[str(a), str(b)], system_prompt="合成提示")
    second = make_config(allowed_course_ids=[str(b), str(a)], system_prompt="合成提示")
    assert first.sha256() == second.sha256()
    assert first == AgentConfiguration.model_validate_json(first.canonical_json())
    assert first.sha256() != make_config(system_prompt="另一提示").sha256()
    assert make_config().allowed_course_ids == ()
    with pytest.raises(ValidationError, match="frozen"):
        first.context.rag_max_messages = 1
    with pytest.raises(ValidationError):
        make_config(allowed_course_ids=[str(a), str(a)])
    ref = {
        "profile_id": "fixture",
        "registry_version": "1.1.0",
        "registry_sha256": "a" * 64,
        "usage": "offline",
    }
    with pytest.raises(ValidationError):
        make_config(evaluation_profiles=[ref, ref])


@pytest.fixture(params=["migration", "metadata"])
def agent_database(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[sqlite3.Connection]:
    path = tmp_path / "agents.db"
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    try:
        if request.param == "migration":
            command.upgrade(Config("alembic.ini"), "head")
            command.check(Config("alembic.ini"))
        else:
            engine = create_engine(f"sqlite:///{path.as_posix()}")
            Base.metadata.create_all(engine)
            engine.dispose()
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
    finally:
        get_settings.cache_clear()


def test_database_enforces_revision_identity_and_fixed_binding(
    agent_database: sqlite3.Connection,
) -> None:
    conn = agent_database
    a, b, r1, r2, chat = (uuid4().hex for _ in range(5))
    config = make_config()
    for profile, name in ((a, "A"), (b, "B")):
        conn.execute("INSERT INTO agent_profiles (id, name) VALUES (?, ?)", (profile, name))
    for revision_id, number in ((r1, 1), (r2, 2)):
        conn.execute(
            "INSERT INTO agent_profile_revisions "
            "(id, agent_profile_id, revision_number, config, config_sha256) VALUES (?,?,?,?,?)",
            (revision_id, a, number, config.canonical_json(), config.sha256()),
        )
    conn.execute(
        "INSERT INTO conversations (id, kind, agent_profile_id, agent_profile_revision_id) "
        "VALUES (?, 'quick', ?, ?)",
        (chat, a, r1),
    )
    conn.commit()

    invalid_statements = [
        (
            "INSERT OR REPLACE INTO agent_profile_revisions "
            "(id, agent_profile_id, revision_number, config, config_sha256) VALUES (?,?,?,?,?)",
            (r1, a, 1, config.canonical_json(), config.sha256()),
        ),
        (
            "INSERT OR REPLACE INTO agent_profile_revisions "
            "(id, agent_profile_id, revision_number, config, config_sha256) VALUES (?,?,?,?,?)",
            (uuid4().hex, a, 1, config.canonical_json(), config.sha256()),
        ),
        (
            "INSERT OR REPLACE INTO conversations "
            "(id, kind, agent_profile_id, agent_profile_revision_id) VALUES (?,'quick',?,?)",
            (chat, a, r2),
        ),
        ("UPDATE agent_profile_revisions SET config='{}' WHERE id=?", (r1,)),
        ("UPDATE agent_profile_revisions SET revision_number=9 WHERE id=?", (r1,)),
        ("DELETE FROM agent_profile_revisions WHERE id=?", (r2,)),
        ("DELETE FROM agent_profiles WHERE id=?", (a,)),
        ("UPDATE conversations SET agent_profile_revision_id=? WHERE id=?", (r2, chat)),
        (
            "UPDATE conversations SET agent_profile_id=NULL, "
            "agent_profile_revision_id=NULL WHERE id=?",
            (chat,),
        ),
        ("INSERT INTO conversations (id, agent_profile_id) VALUES (?,?)", (uuid4().hex, a)),
        (
            "INSERT INTO conversations (id, agent_profile_revision_id) VALUES (?,?)",
            (uuid4().hex, r1),
        ),
        (
            "INSERT INTO conversations (id, agent_profile_id, agent_profile_revision_id) "
            "VALUES (?,?,?)",
            (uuid4().hex, b, r1),
        ),
        (
            "INSERT INTO conversations (id, agent_profile_id, agent_profile_revision_id) "
            "VALUES (?,?,?)",
            (uuid4().hex, a, uuid4().hex),
        ),
        (
            "INSERT INTO agent_profile_revisions "
            "(id, agent_profile_id, revision_number, config, config_sha256) VALUES (?,?,?,?,?)",
            (uuid4().hex, a, 1, config.canonical_json(), config.sha256()),
        ),
        (
            "INSERT INTO agent_profile_revisions "
            "(id, agent_profile_id, revision_number, config, config_sha256) VALUES (?,?,?,?,?)",
            (uuid4().hex, a, 0, config.canonical_json(), config.sha256()),
        ),
        (
            "INSERT INTO agent_profile_revisions "
            "(id, agent_profile_id, revision_number, config, config_sha256) VALUES (?,?,?,?,?)",
            (uuid4().hex, a, 3, "null", config.sha256()),
        ),
        (
            "INSERT INTO agent_profile_revisions "
            "(id, agent_profile_id, revision_number, config, config_sha256) VALUES (?,?,?,?,?)",
            (uuid4().hex, a, 3, config.canonical_json(), "invalid"),
        ),
    ]
    for sql, parameters in invalid_statements:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, parameters)
    conn.execute("UPDATE agent_profiles SET enabled=0 WHERE id=?", (a,))
    conn.execute("UPDATE conversations SET title='updated' WHERE id=?", (chat,))
    assert conn.execute(
        "SELECT agent_profile_revision_id FROM conversations WHERE id=?", (chat,)
    ).fetchone() == (r1,)
    assert conn.execute("SELECT count(*) FROM agent_profile_revisions").fetchone() == (2,)

    legacy = uuid4().hex
    conn.execute("INSERT INTO conversations (id, kind) VALUES (?, 'quick')", (legacy,))
    with pytest.raises(sqlite3.IntegrityError, match="binding is immutable"):
        conn.execute(
            "UPDATE conversations SET agent_profile_id=?, agent_profile_revision_id=? WHERE id=?",
            (a, r1, legacy),
        )
    # Ordinary conversation deletion remains supported and does not remove profiles.
    conn.execute("DELETE FROM conversations WHERE id=?", (chat,))
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


async def test_orm_hash_validation_append_and_bulk_update_guard(db_session: AsyncSession) -> None:
    profile = AgentProfile(name="fixture agent")
    db_session.add(profile)
    await db_session.flush()
    first = AgentProfileRevision(
        agent_profile_id=profile.id,
        revision_number=1,
        config=make_config().model_dump(mode="json"),
    )
    db_session.add(first)
    await db_session.flush()
    assert first.read_config() == make_config()
    conversation = Conversation(
        kind=ConversationKind.QUICK,
        agent_profile_id=profile.id,
        agent_profile_revision_id=first.id,
    )
    db_session.add(conversation)
    await db_session.flush()
    second = AgentProfileRevision(
        agent_profile_id=profile.id,
        revision_number=2,
        config=make_config(system_prompt="changed").model_dump(mode="json"),
    )
    db_session.add(second)
    await db_session.commit()
    await db_session.refresh(conversation)
    assert conversation.agent_profile_revision_id == first.id
    latest = await db_session.scalar(
        select(AgentProfileRevision)
        .where(AgentProfileRevision.agent_profile_id == profile.id)
        .order_by(AgentProfileRevision.revision_number.desc())
        .limit(1)
    )
    assert latest is second
    with pytest.raises(IntegrityError, match="immutable"):
        await db_session.execute(update(AgentProfileRevision).values(change_summary="overwrite"))
    await db_session.rollback()


async def test_orm_rejects_mismatched_hash(db_session: AsyncSession) -> None:
    profile = AgentProfile(name="hash fixture")
    db_session.add(profile)
    await db_session.flush()
    revision = AgentProfileRevision(
        agent_profile_id=profile.id,
        revision_number=1,
        config=make_config().model_dump(mode="json"),
        config_sha256="0" * 64,
    )
    db_session.add(revision)
    with pytest.raises(ValueError, match="hash mismatch"):
        await db_session.flush()
    await db_session.rollback()
    with pytest.raises(ValueError, match="hash mismatch"):
        revision.read_config()


LEGACY_TABLES = ("courses", "documents", "conversations", "messages", "token_usage_events")


def legacy_snapshot(conn: sqlite3.Connection) -> dict[str, list[tuple[Any, ...]]]:
    result = {}
    for table in LEGACY_TABLES:
        columns = [
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})")
            if row[1] not in {"agent_profile_id", "agent_profile_revision_id"}
        ]
        result[table] = conn.execute(
            f"SELECT {','.join(columns)} FROM {table} ORDER BY id"
        ).fetchall()
    return result


def test_populated_legacy_copy_survives_upgrade_downgrade_and_reupgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "legacy.db", tmp_path / "copy.db"
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{source.as_posix()}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "20260810_04")
        course, document, course_chat, quick_chat = (uuid4().hex for _ in range(4))
        with sqlite3.connect(source) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("INSERT INTO courses(id,name) VALUES (?, 'fixture course')", (course,))
            conn.execute(
                "INSERT INTO documents"
                "(id,course_id,original_name,stored_name,file_type,file_size,sha256,status) "
                "VALUES (?,?,'fixture.txt','fixture.txt','txt',10,?,'completed')",
                (document, course, "a" * 64),
            )
            conn.execute(
                "INSERT INTO conversations(id,kind,course_id) VALUES (?,'course',?)",
                (course_chat, course),
            )
            conn.execute(
                "INSERT INTO conversations(id,kind) VALUES (?,'quick')",
                (quick_chat,),
            )
            for chat in (course_chat, quick_chat):
                conn.execute(
                    "INSERT INTO messages(id,conversation_id,sequence_number,role,"
                    "content,citations,"
                    "retrieval,usage,model) VALUES (?,?,1,'assistant','synthetic answer',?,?,?,?)",
                    (
                        uuid4().hex,
                        chat,
                        '[{"fixture":"citation"}]',
                        '{"fixture":1}',
                        '{"output_tokens":7}',
                        "fixture-model",
                    ),
                )
            conn.execute(
                "INSERT INTO token_usage_events(id,model,output_tokens) VALUES (?,?,7)",
                (uuid4().hex, "fixture-model"),
            )
            conn.commit()
            before = legacy_snapshot(conn)
            with sqlite3.connect(target) as copy:
                conn.backup(copy)
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{target.as_posix()}")
        get_settings.cache_clear()
        command.upgrade(config, "head")
        command.check(config)
        with sqlite3.connect(target) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            assert legacy_snapshot(conn) == before
            assert conn.execute(
                "SELECT agent_profile_id,agent_profile_revision_id FROM conversations"
            ).fetchall() == [(None, None), (None, None)]
            profile, revision_id, new_chat = (uuid4().hex for _ in range(3))
            snapshot = make_config()
            conn.execute("INSERT INTO agent_profiles(id,name) VALUES (?, 'new agent')", (profile,))
            conn.execute(
                "INSERT INTO agent_profile_revisions"
                "(id,agent_profile_id,revision_number,config,config_sha256) VALUES (?,?,1,?,?)",
                (revision_id, profile, snapshot.canonical_json(), snapshot.sha256()),
            )
            conn.execute(
                "INSERT INTO conversations(id,kind,agent_profile_id,agent_profile_revision_id) "
                "VALUES (?,'quick',?,?)",
                (new_chat, profile, revision_id),
            )
            conn.execute(
                "INSERT INTO messages(id,conversation_id,sequence_number,role,content,citations) "
                "VALUES (?,?,1,'user','new synthetic message','[]')",
                (uuid4().hex, new_chat),
            )
            before_downgrade = legacy_snapshot(conn)
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        command.downgrade(config, "20260810_04")
        with sqlite3.connect(target) as conn:
            assert legacy_snapshot(conn) == before_downgrade
            assert (
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE name LIKE 'agent_profile%'"
                ).fetchall()
                == []
            )
        command.upgrade(config, "head")
        command.check(config)
        with sqlite3.connect(target) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            assert legacy_snapshot(conn) == before_downgrade
            assert conn.execute("SELECT count(*) FROM agent_profiles").fetchone() == (0,)
            # Existing course cascade semantics still hold after two rebuilds.
            conn.execute("DELETE FROM courses WHERE id=?", (course,))
            assert conn.execute(
                "SELECT count(*) FROM messages WHERE conversation_id=?", (course_chat,)
            ).fetchone() == (0,)
            assert conn.execute(
                "SELECT count(*) FROM messages WHERE conversation_id=?", (quick_chat,)
            ).fetchone() == (1,)
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with sqlite3.connect(source) as conn:
            assert legacy_snapshot(conn) == before
    finally:
        get_settings.cache_clear()


async def test_profile_row_version_rejects_stale_edits(db_session: AsyncSession) -> None:
    from sqlalchemy.orm.exc import StaleDataError

    profile = AgentProfile(name="concurrent fixture")
    db_session.add(profile)
    await db_session.commit()
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as other:
        stale = await other.get(AgentProfile, profile.id)
        assert stale is not None
        profile.description = "first editor"
        await db_session.commit()
        assert profile.row_version == 2
        stale.description = "second editor"
        with pytest.raises(StaleDataError):
            await other.commit()
        await other.rollback()
    await db_session.refresh(profile)
    assert profile.description == "first editor"
