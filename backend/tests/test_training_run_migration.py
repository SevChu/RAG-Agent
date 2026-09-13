from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import Settings, get_settings
from tests.test_agent_profiles import make_config


def test_run_migration_preserves_registry_and_agent_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "runs-migration.db"
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    config = Config("alembic.ini")
    agent, agent_revision, dataset, revision, review, run = (uuid4().hex for _ in range(6))
    try:
        command.upgrade(config, "20260911_07")
        with sqlite3.connect(path) as conn:
            frozen = make_config()
            conn.execute("INSERT INTO agent_profiles(id,name) VALUES (?,'fixture')", (agent,))
            conn.execute(
                "INSERT INTO agent_profile_revisions(id,agent_profile_id,revision_"
                "number,config,config_sha256) VALUES (?,?,1,?,?)",
                (agent_revision, agent, frozen.canonical_json(), frozen.sha256()),
            )
            conn.execute("INSERT INTO training_datasets(id,name) VALUES (?,'fixture')", (dataset,))
            conn.execute(
                "INSERT INTO training_dataset_revisions(id,dataset_id,revision_num"
                "ber,manifest,manifest_sha256,report) VALUES (?,?,1,'{}',?,'{}')",
                (revision, dataset, "a" * 64),
            )
            conn.execute(
                "INSERT INTO training_dataset_reviews(id,revision_id,sequence,stat"
                "us,reviewer,note) VALUES (?,?,1,'approved','fixture','synthetic')",
                (review, revision),
            )
            conn.commit()
            old_tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name<>'alembic_version'"
                )
            ]
            before = {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in old_tables}
            triggers = conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            ).fetchall()
        for target in ("head", "20260911_07", "head"):
            if target == "head":
                command.upgrade(config, target)
                command.check(config)
            else:
                command.downgrade(config, target)
            with sqlite3.connect(path) as conn:
                assert {
                    name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in old_tables
                } == before
                assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
                current = conn.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
                ).fetchall()
                assert set(triggers) <= set(current)
                if target == "head":
                    from app.models.training_run import TRIGGERS

                    assert set(TRIGGERS) <= {name for name, _ in current}
                    conn.execute(
                        "INSERT INTO training_runs(id,agent_profile_id,agent_revision_id,d"
                        "ataset_revision_id,"
                        "idempotency_key,request_sha256,snapshot,snapshot_sha256,total_steps) "
                        "VALUES (?,?,?,?,?,?,?, ?,3)",
                        (
                            run,
                            agent,
                            agent_revision,
                            revision,
                            uuid4().hex,
                            "b" * 64,
                            '{"source_course_ids":[]}',
                            "c" * 64,
                        ),
                    )
                    assert conn.execute(
                        "SELECT phase FROM training_events WHERE run_id=?", (run,)
                    ).fetchone() == ("queued",)
                    conn.execute("UPDATE agent_profiles SET enabled=0 WHERE id=?", (agent,))
                    assert conn.execute(
                        "SELECT status FROM training_runs WHERE id=?", (run,)
                    ).fetchone() == ("cancelled",)
                    assert conn.execute(
                        "SELECT sequence FROM training_events WHERE run_id=? ORDER BY sequence",
                        (run,),
                    ).fetchall() == [(1,), (2,)]
                    with pytest.raises(sqlite3.IntegrityError, match="invalid training state"):
                        conn.execute(
                            "UPDATE training_runs SET status='succeeded' WHERE id=?", (run,)
                        )
                    conn.execute("UPDATE agent_profiles SET enabled=1 WHERE id=?", (agent,))
                    conn.commit()
                else:
                    assert len(current) == len(triggers)
                    assert not conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='training_runs'"
                    ).fetchall()
    finally:
        get_settings.cache_clear()
