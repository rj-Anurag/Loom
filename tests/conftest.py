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
