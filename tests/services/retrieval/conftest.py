"""Fixtures for retrieval module tests (Providers, Grouping, Summarizer, Score Boost)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.models import Agent, Project

pytestmark = pytest.mark.asyncio

# ── Standard fixtures (reused across retrieval test files) ────────────────────


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    """Create a minimal project for retrieval tests."""
    p = Project(name="retrieval-test")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession, test_project: Project) -> Agent:
    """Create an agent belonging to the test project."""
    a = Agent(project_id=test_project.id, kind="local")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


@pytest_asyncio.fixture
async def stub_llm():
    """A StubLLMProvider instance for deterministic test summarization.

    Defined here rather than in test modules so all retrieval tests
    share the same pattern.
    """
    from loom.services.retrieval.providers import StubLLMProvider

    return StubLLMProvider()


@pytest_asyncio.fixture
async def mock_redis():
    """An AsyncMock-based fake Redis for unit-level tests.

    Supports the subset of Redis commands used by the summarizer worker:
    ``set`` with ``nx``/``ex`` (lock acquire), ``delete`` (lock release),
    and ``exists``.

    * First ``set(..., nx=True)`` call returns ``True``.
    * Subsequent ``set(..., nx=True)`` calls with the same key return ``False``.
    * ``delete(key)`` removes the key and returns ``1``.
    * ``exists(key)`` returns ``1`` if key is held, ``0`` otherwise.
    """
    mock: AsyncMock = AsyncMock()

    _store: dict[str, str] = {}

    async def _set(key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx:
            if key in _store:
                return False
            _store[key] = value
            return True
        _store[key] = value
        return True

    async def _delete(key: str) -> int:
        return 1 if _store.pop(key, None) is not None else 0

    async def _exists(key: str) -> int:
        return 1 if key in _store else 0

    mock.set.side_effect = _set
    mock.delete.side_effect = _delete
    mock.exists.side_effect = _exists

    return mock


# ── DB helpers ────────────────────────────────────────────────────────────────


def _aligned_window_start(window_minutes: int = 30) -> datetime:
    """Return a datetime well within the current aligned time window.

    Ensures test fixtures create units that don't accidentally straddle
    window boundaries.
    """
    now = datetime.now(UTC)
    epoch = int(now.timestamp())
    aligned_epoch = (epoch // (window_minutes * 60)) * (window_minutes * 60) + 120
    return datetime.fromtimestamp(aligned_epoch, tz=UTC)


@pytest_asyncio.fixture
async def stub_embedder():
    """A StubProvider instance for deterministic embedding in tests.

    Always available — no external dependencies required.
    """
    from loom.services.retrieval.providers import StubProvider

    return StubProvider()


@pytest_asyncio.fixture
async def embedded_sample_units(
    db_session: AsyncSession,
    test_project: Project,
    test_agent: Agent,
) -> dict[str, uuid.UUID]:
    """Insert units with deterministic embeddings for search tests.

    Returns a dict mapping semantic labels to unit IDs.
    """
    from loom.services.retrieval.providers import StubProvider

    provider = StubProvider()
    units = {
        "security_bcrypt": "Use bcrypt for password hashing to comply with security policies",
        "redis_cache": "Implement Redis caching layer for frequently accessed context",
        "auth_flow": "The authentication flow uses JWT tokens with a 24-hour expiry",
        "db_schema": "PostgreSQL schema with pgvector for embedding storage",
        "weather_noise": "The weather today is sunny with a chance of rain",
    }

    unit_ids: dict[str, uuid.UUID] = {}
    for label, content in units.items():
        unit_id = uuid.uuid4()
        embedding = await provider.embed(content)

        await db_session.execute(
            text("""
                INSERT INTO context_units
                    (id, project_id, agent_id, client_uuid, type, trust_tier,
                     content, embedding, version, created_at)
                VALUES
                    (:id, :pid, :aid, :cuuid, :type, :tier,
                     :content, CAST(:embedding AS vector), :version, :created_at)
            """),
            {
                "id": unit_id,
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "decision",
                "tier": "agent",
                "content": content,
                "embedding": str(embedding),
                "version": 1,
                "created_at": datetime.now(UTC),
            },
        )
        unit_ids[label] = unit_id

    await db_session.commit()
    return unit_ids


async def _insert_unit(
    db_session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
    content: str,
    *,
    type_: str = "message",
    trust_tier: str = "agent",
    created_at: datetime | None = None,
) -> uuid.UUID:
    """Insert a context unit for test scenarios.

    Returns the generated unit ID.
    """
    unit_id = uuid.uuid4()
    if created_at is None:
        created_at = datetime.now(UTC)

    await db_session.execute(
        text(
            "INSERT INTO context_units "
            "(id, project_id, agent_id, client_uuid, type, trust_tier, "
            "content, version, created_at) "
            "VALUES (:id, :pid, :aid, :cuuid, :type, :tier, :content, :version, :created_at)"
        ),
        {
            "id": unit_id,
            "pid": project_id,
            "aid": agent_id,
            "cuuid": uuid.uuid4(),
            "type": type_,
            "tier": trust_tier,
            "content": content,
            "version": 1,
            "created_at": created_at,
        },
    )
    await db_session.commit()
    return unit_id


# ── Data fixtures for grouping / summarizer tests ────────────────────────────


@pytest_asyncio.fixture
async def sample_units_in_window(
    db_session: AsyncSession,
    test_project: Project,
    test_agent: Agent,
) -> list[uuid.UUID]:
    """8 units within a single 30-minute time window, oldest first.

    All units have unique timestamps so ordering tests can verify
    chronological sort.
    """
    window_start = _aligned_window_start(window_minutes=30)
    ids: list[uuid.UUID] = []
    for i in range(8):
        created_at = window_start + timedelta(seconds=i * 30)
        uid = await _insert_unit(
            db_session,
            test_project.id,
            test_agent.id,
            f"Sample unit {i} — decision content for testing",
            created_at=created_at,
        )
        ids.append(uid)
    return ids


@pytest_asyncio.fixture
async def few_recent_units(
    db_session: AsyncSession,
    test_project: Project,
    test_agent: Agent,
) -> list[uuid.UUID]:
    """Only 2 units (below typical ``min_units`` threshold of 5)."""
    window_start = _aligned_window_start(window_minutes=30)
    ids: list[uuid.UUID] = []
    for i in range(2):
        created_at = window_start + timedelta(seconds=i * 30)
        uid = await _insert_unit(
            db_session,
            test_project.id,
            test_agent.id,
            f"Recent unit {i}",
            created_at=created_at,
        )
        ids.append(uid)
    return ids


@pytest_asyncio.fixture
async def mixed_tier_units(
    db_session: AsyncSession,
    test_project: Project,
    test_agent: Agent,
) -> list[uuid.UUID]:
    """4 units with mixed trust tiers: user, agent, external_tool, agent.

    Spread across a window so they can be grouped together.
    """
    window_start = _aligned_window_start(window_minutes=30)
    entries: list[tuple[str, str]] = [
        ("user", "User-level observation — high trust"),
        ("agent", "Agent finding — medium trust"),
        ("external_tool", "Tool output — low trust"),
        ("agent", "Another agent note — medium trust"),
    ]
    ids: list[uuid.UUID] = []
    for i, (tier, content) in enumerate(entries):
        created_at = window_start + timedelta(seconds=i * 20)
        uid = await _insert_unit(
            db_session,
            test_project.id,
            test_agent.id,
            content,
            type_="message",
            trust_tier=tier,
            created_at=created_at,
        )
        ids.append(uid)
    return ids
