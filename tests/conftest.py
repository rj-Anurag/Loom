from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from loom.api.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean AsyncSession per test.

    ``asyncio_default_fixture_loop_scope = "session"`` in ``pyproject.toml``
    ensures all async fixtures/tests share one event loop, so the asyncpg
    connection pool's connections are always on the correct loop.
    """
    from loom.db import async_session_factory

    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator:  # type: ignore[type-arg]
    """Provide a Redis client connected to test database 1.

    Flushes the database before and after each test so every test starts
    with a clean state.  This fixture is re-usable across lock tests and
    coordination tests that need to verify Redis availability / fallback.

    Import ``redis.asyncio`` lazily to avoid requiring the dependency
    for tests that don't use Redis.
    """
    import redis.asyncio as redis_async

    r = redis_async.from_url("redis://localhost:6379/1", decode_responses=True)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.close()
