from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import Settings, get_settings
from tests.test_agent_profiles import make_config

OLD_TABLES = (
    "courses",
    "documents",
    "conversations",
    "messages",
    "token_usage_events",
    "agent_profiles",
    "agent_profile_revisions",
)


def snapshot(connection: sqlite3.Connection) -> dict[str, list[tuple[Any, ...]]]:
    return {
        table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        for table in OLD_TABLES
    }


def test_training_migration_preserves_all_old_rows_and_triggers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, copy = tmp_path / "old.db", tmp_path / "rehearsal.db"
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{source.as_posix()}")
    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    try:
        command.upgrade(cfg, "20260910_06")
        course, document, agent, revision, course_chat, quick_chat = (uuid4().hex for _ in range(6))
        configuration = make_config(allowed_course_ids=[course])
        with sqlite3.connect(source) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("INSERT INTO courses(id,name) VALUES (?, 'synthetic')", (course,))
            conn.execute(
                "INSERT INTO documents"
                "(id,course_id,original_name,stored_name,file_type,file_size,sha256,status) "
                "VALUES (?,?,'synthetic.txt','synthetic.txt','txt',10,?,'completed')",
                (document, course, "a" * 64),
            )
            conn.execute("INSERT INTO agent_profiles(id,name) VALUES (?, 'synthetic')", (agent,))
            conn.execute(
                "INSERT INTO agent_profile_revisions"
                "(id,agent_profile_id,revision_number,config,config_sha256) VALUES (?,?,1,?,?)",
                (revision, agent, configuration.canonical_json(), configuration.sha256()),
            )
            conn.execute(
                "INSERT INTO conversations(id,kind,course_id,agent_profile_id,"
                "agent_profile_revision_id) VALUES (?,'course',?,?,?)",
                (course_chat, course, agent, revision),
            )
            conn.execute("INSERT INTO conversations(id,kind) VALUES (?,'quick')", (quick_chat,))
            for chat in (course_chat, quick_chat):
                conn.execute(
                    "INSERT INTO messages(id,conversation_id,sequence_number,role,content,"
                    "citations,retrieval,usage,model) VALUES (?,?,1,'assistant','synthetic',"
                    "'[]','{}','{}','fixture-model')",
                    (uuid4().hex, chat),
                )
            conn.execute(
                "INSERT INTO token_usage_events(id,model,output_tokens) VALUES (?,?,7)",
                (uuid4().hex, "fixture-model"),
            )
            conn.commit()
            before = snapshot(conn)
            triggers = conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            ).fetchall()
            with sqlite3.connect(copy) as target:
                conn.backup(target)
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{copy.as_posix()}")
        get_settings.cache_clear()
        for target in ("head", "20260910_06", "head"):
            if target == "head":
                command.upgrade(cfg, target)
                command.check(cfg)
            else:
                command.downgrade(cfg, target)
            with sqlite3.connect(copy) as conn:
                assert snapshot(conn) == before
                assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
                assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                current = conn.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
                ).fetchall()
                assert set(triggers) <= set(current)
                if target == "head":
                    assert {
                        prefix + suffix
                        for prefix in ("training_revision", "training_review")
                        for suffix in ("_no_update", "_no_delete", "_no_replace")
                    } <= {row[0] for row in current}
                    did, rid, review_id = (uuid4().hex for _ in range(3))
                    conn.execute(
                        "INSERT INTO training_datasets(id,name) VALUES (?,?)", (did, "synthetic")
                    )
                    conn.execute(
                        "INSERT INTO training_dataset_revisions(id,dataset_id,revision_number,"
                        "manifest,manifest_sha256,report) VALUES (?,?,1,'{}',?,'{}')",
                        (rid, did, "b" * 64),
                    )
                    conn.execute(
                        "INSERT INTO training_dataset_reviews(id,revision_id,sequence,status,"
                        "reviewer,note) VALUES (?,?,1,'draft','fixture','synthetic')",
                        (review_id, rid),
                    )
                    for table in ("training_dataset_revisions", "training_dataset_reviews"):
                        for sql in (
                            f"UPDATE {table} SET id=id",
                            f"DELETE FROM {table}",
                            f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}",
                        ):
                            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                                conn.execute(sql)
                    conn.commit()
                else:
                    assert not conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name LIKE 'training_%'"
                    ).fetchall()
        with sqlite3.connect(source) as conn:
            assert snapshot(conn) == before
    finally:
        get_settings.cache_clear()
