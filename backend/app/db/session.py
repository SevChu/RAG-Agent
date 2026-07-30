from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import ConnectionPoolEntry

from app.core.config import get_settings


def enable_sqlite_foreign_keys(
    dbapi_connection: DBAPIConnection,
    _: ConnectionPoolEntry,
) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_database_engine(database_url: str) -> AsyncEngine:
    database_engine = create_async_engine(database_url, pool_pre_ping=True)
    if make_url(database_url).get_backend_name() == "sqlite":
        event.listen(
            database_engine.sync_engine,
            "connect",
            enable_sqlite_foreign_keys,
        )
    return database_engine


settings = get_settings()
engine = create_database_engine(settings.database_url)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
