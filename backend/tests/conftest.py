from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import create_database_engine, get_session
from app.indexing import DocumentIndexingManager, get_indexing_manager
from app.main import app
from app.models import Course, Document  # noqa: F401


@pytest_asyncio.fixture
async def db_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    database_path = (tmp_path / "test.db").as_posix()
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path}")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def api_settings(tmp_path: Path) -> AsyncIterator[Settings]:
    database_path = (tmp_path / "api.db").as_posix()
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{database_path}",
        upload_dir=tmp_path / "uploads",
        qdrant_path=tmp_path / "qdrant",
        auto_index_documents=False,
        max_upload_mb=1,
    )
    yield settings


@pytest_asyncio.fixture
async def api_client(api_settings: Settings) -> AsyncIterator[AsyncClient]:
    engine = create_database_engine(api_settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def override_settings() -> Settings:
        return api_settings

    indexing_manager = DocumentIndexingManager(api_settings, session_factory)

    def override_indexing_manager() -> DocumentIndexingManager:
        return indexing_manager

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = override_settings
    app.dependency_overrides[get_indexing_manager] = override_indexing_manager
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await indexing_manager.close()
    await engine.dispose()
