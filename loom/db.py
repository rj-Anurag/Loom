from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from loom.config import settings

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _init_db():
    """Lazy-initialize the engine and session factory on the calling event loop.

    Uses ``NullPool`` so every session opens a new asyncpg connection (no
    cross-Task contamination within the same event loop).  This is essential
    for ``TestClient`` compatibility since each HTTP request runs in a
    separate anyio task but asyncpg connections are scoped to a single task.
    """
    global _engine, _session_factory
    if _engine is not None:
        return
    _engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


# Module-level __getattr__ preserves existing `from loom.db import async_session_factory` imports
# while deferring engine creation until first use (fixes asyncpg + TestClient event loop conflict).
def __getattr__(name: str):
    if name == "engine":
        _init_db()
        assert _engine is not None
        return _engine
    if name == "async_session_factory":
        _init_db()
        assert _session_factory is not None
        return _session_factory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class Base(DeclarativeBase):
    pass


async def get_session():
    _init_db()
    factory = _session_factory
    assert factory is not None
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()
