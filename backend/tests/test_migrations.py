import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch

from app.core.config import get_settings


def test_initial_migration_upgrades_matches_models_and_downgrades(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    try:
        command.upgrade(config, "head")
        command.check(config)

        with sqlite3.connect(database_path) as connection:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            document_ddl = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
            ).fetchone()

        assert {"alembic_version", "courses", "documents"} <= table_names
        assert document_ddl is not None
        assert "ON DELETE CASCADE" in document_ddl[0]
        assert "completed" in document_ddl[0]
        assert "uq_documents_course_id_sha256" in document_ddl[0]

        command.downgrade(config, "base")

        with sqlite3.connect(database_path) as connection:
            remaining_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert "courses" not in remaining_tables
        assert "documents" not in remaining_tables
    finally:
        get_settings.cache_clear()
