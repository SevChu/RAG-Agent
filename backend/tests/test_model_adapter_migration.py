from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import Settings, get_settings
from app.models.model_adapter import TRIGGERS
from tests.test_agent_profiles import make_config


def test_adapter_migration_roundtrip_retains_prior_business(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "migration.db"
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    try:
        command.upgrade(cfg, "20260911_08")
        with sqlite3.connect(path) as conn:
            agent, rev = uuid4().hex, uuid4().hex
            frozen = make_config()
            conn.execute("INSERT INTO agent_profiles(id,name) VALUES (?,'synthetic')", (agent,))
            conn.execute(
                "INSERT INTO agent_profile_revisions(id,agent_profile_id,revision_number,"
                "config,config_sha256) VALUES (?,?,1,?,?)",
                (rev, agent, frozen.canonical_json(), frozen.sha256()),
            )
            conn.commit()
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name<>'alembic_version'"
                )
            ]
            baseline = {t: conn.execute(f'SELECT * FROM "{t}"').fetchall() for t in tables}
            triggers = conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        for direction, target in (
            ("up", "20260911_09"),
            ("down", "20260911_08"),
            ("up", "20260911_09"),
        ):
            (command.upgrade if direction == "up" else command.downgrade)(cfg, target)
            with sqlite3.connect(path) as conn:
                assert baseline == {
                    t: conn.execute(f'SELECT * FROM "{t}"').fetchall() for t in tables
                }
                current = conn.execute(
                    "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
                ).fetchall()
                assert set(triggers) <= set(current)
                assert len(current) == len(triggers) + (4 if direction == "up" else 0)
                assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
                if direction == "up":
                    assert set(TRIGGERS) <= {r[0] for r in current}
            if direction == "up":
                command.check(cfg)
    finally:
        get_settings.cache_clear()
