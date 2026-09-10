from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings

# Historical fixtures authenticate with agent UUIDs. Production defaults this
# compatibility path off; tests retain it while exercising legacy migrations.
settings.allow_legacy_uuid_tokens = True


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

    Also sets ``loom.config.settings.redis_url`` to DB 1 so the app's
    module-level Redis singleton (``get_redis`` dependency) uses the
    same database as the test fixture.

    Import ``redis.asyncio`` lazily to avoid requiring the dependency
    for tests that don't use Redis.
    """
    import redis.asyncio as redis_async

    import loom.config

    # Point the app's Redis config to DB 1 so get_redis() uses the
    # same database as this test fixture.
    original_url = loom.config.settings.redis_url
    loom.config.settings.redis_url = "redis://localhost:6379/1"

    # Reset the module-level singleton so the next get_redis() call
    # picks up the test DB URL.
    import loom.services.retrieval.queue as queue_module

    queue_module._redis = None

    r = redis_async.from_url("redis://localhost:6379/1", decode_responses=True)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()
    loom.config.settings.redis_url = original_url
