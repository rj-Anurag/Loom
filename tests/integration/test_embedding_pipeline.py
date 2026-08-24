"""Tests for Phase 1.9 — Async Embedding Pipeline.

Covers queue enqueue, providers, worker loop, DLQ, and write-path integration.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


# ── Fixtures ──────────────────────────────────────────────────────────────────




@pytest_asyncio.fixture
async def client() -> AsyncClient:
    from loom.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    from loom.db import async_session_factory

    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession) -> Project:
    """Create a minimal project for integration tests."""
    from loom.models.projects import Project

    p = Project(name="embedding-test")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def test_agent(db_session: AsyncSession, test_project: Project) -> Agent:
    from loom.models.agents import Agent

    a = Agent(project_id=test_project.id, kind="local")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


@pytest_asyncio.fixture
async def auth_headers(test_agent: Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {test_agent.id}"}


# ── Provider Tests ────────────────────────────────────────────────────────────


class TestStubProvider:
    """StubProvider unit tests — no Redis needed."""

    @pytest.mark.parametrize("content", ["hello world", "a" * 5000, ""])
    async def test_returns_1536_vector(self, content: str) -> None:
        """StubProvider always returns a 1536-dimensional vector."""
        from loom.services.retrieval.providers import StubProvider

        provider = StubProvider()
        vector = await provider.embed(content)
        if not content.strip():
            assert vector is None
        else:
            assert len(vector) == 1536
            assert all(isinstance(v, float) for v in vector)

    async def test_deterministic(self) -> None:
        """Same content produces the same vector."""
        from loom.services.retrieval.providers import StubProvider

        provider = StubProvider()
        v1 = await provider.embed("deterministic test")
        v2 = await provider.embed("deterministic test")
        assert v1 == v2

    async def test_different_content_different_vectors(self) -> None:
        """Different content produces (with overwhelming probability) different vectors."""
        from loom.services.retrieval.providers import StubProvider

        provider = StubProvider()
        v1 = await provider.embed("content A")
        v2 = await provider.embed("content B")
        assert v1 != v2

    async def test_normalized_output(self) -> None:
        """StubProvider returns vectors suitable for cosine-similarity search (unit length)."""
        import math

        from loom.services.retrieval.providers import StubProvider

        provider = StubProvider()
        vector = await provider.embed("check normalization")
        assert vector is not None
        magnitude = math.sqrt(sum(v * v for v in vector))
        # Allow floating-point tolerance: magnitude should be ~1.0
        assert abs(magnitude - 1.0) < 0.01, f"Expected unit vector, got magnitude {magnitude}"


# ── Queue Tests ────────────────────────────────────────────────────────────────


class TestEmbeddingQueue:
    """Tests for the Redis-backed embedding job queue."""

    async def test_enqueue_adds_job(self, redis_client) -> None:
        """enqueue_embedding_job pushes a well-formed job onto the queue."""
        from loom.services.retrieval.queue import enqueue_embedding_job

        uid = str(uuid.uuid4())
        await enqueue_embedding_job(uid, "test content")

        queue_len = await redis_client.llen("embedding:queue")
        assert queue_len == 1

        raw = await redis_client.lpop("embedding:queue")
        assert raw is not None
        job = json.loads(raw)
        assert job["context_unit_id"] == uid
        assert job["attempt"] == 0
        assert "content" in job

    async def test_enqueue_truncates_long_content(self, redis_client) -> None:
        """Content exceeding 5000 chars is truncated in the queue payload."""
        from loom.services.retrieval.queue import enqueue_embedding_job

        long_content = "x" * 10000
        await enqueue_embedding_job(str(uuid.uuid4()), long_content)

        raw = await redis_client.lpop("embedding:queue")
        assert raw is not None
        job = json.loads(raw)
        assert len(job["content"]) == 5000

    async def test_enqueue_does_not_raise_on_redis_down(self) -> None:
        """A Redis failure must not propagate — enqueue is fire-and-forget."""
        from loom.services.retrieval.queue import enqueue_embedding_job

        with patch("loom.services.retrieval.queue.get_redis") as mock:
            mock.side_effect = ConnectionError("Redis unreachable")
            # Should not raise
            await enqueue_embedding_job(str(uuid.uuid4()), "test")

    async def test_enqueue_after_write(
        self, client, test_project: Project, auth_headers, redis_client
    ) -> None:
        """After a successful context write, a job appears in the embedding queue."""
        body = {
            "client_uuid": str(uuid.uuid4()),
            "type": "message",
            "content": "Test content for embedding",
            "version": 1,
        }
        resp = await client.post(
            f"/v1/projects/{test_project.id}/context",
            json=body,
            headers=auth_headers,
        )
        assert resp.status_code == 201

        queue_len = await redis_client.llen("embedding:queue")
        assert queue_len == 1


# ── Worker Tests ────────────────────────────────────────────────────────────────


class TestEmbeddingWorker:
    """Integration tests for the embedding worker loop."""

    async def test_worker_processes_job_and_updates_db(
        self, redis_client, db_session: AsyncSession, test_project: Project,
        test_agent: Agent,
    ) -> None:
        """Worker picks up a job, computes embedding, and updates the DB row."""
        from loom.services.retrieval.embedding_worker import process_embedding_job

        # Create a context unit using the real project and agent
        unit_id = uuid.uuid4()
        await db_session.execute(
            text(
                "INSERT INTO context_units "
                "(id, project_id, agent_id, client_uuid, type, trust_tier, content, version) "
                "VALUES (:id, :pid, :aid, :cuuid, :type, :tier, :content, :version)"
            ),
            {
                "id": unit_id,
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "message",
                "tier": "agent",
                "content": "Embed me!",
                "version": 1,
            },
        )
        await db_session.commit()

        # Process it
        await process_embedding_job(unit_id, "Embed me!")

        # Verify the embedding was set via ORM (handles pgvector type correctly)
        from loom.models.context_units import ContextUnit

        unit = await db_session.get(ContextUnit, unit_id)
        assert unit is not None
        assert unit.embedding is not None
        assert len(unit.embedding) == 1536

    async def test_worker_skips_nonexistent_unit(
        self, redis_client, db_session: AsyncSession
    ) -> None:
        """Worker gracefully skips jobs for units that don't exist (no crash)."""
        from loom.services.retrieval.embedding_worker import process_embedding_job

        await process_embedding_job(uuid.uuid4(), "content for ghost unit")

    async def test_worker_raises_on_failure(
        self, db_session: AsyncSession, test_project: Project,
        test_agent: Agent,
    ) -> None:
        """When embedding raises, the exception propagates from process_embedding_job."""
        from loom.services.retrieval.embedding_worker import process_embedding_job

        # Create a context unit using the real project and agent
        unit_id = uuid.uuid4()
        await db_session.execute(
            text(
                "INSERT INTO context_units "
                "(id, project_id, agent_id, client_uuid, type, trust_tier, content, version) "
                "VALUES (:id, :pid, :aid, :cuuid, :type, :tier, :content, :version)"
            ),
            {
                "id": unit_id,
                "pid": test_project.id,
                "aid": test_agent.id,
                "cuuid": uuid.uuid4(),
                "type": "message",
                "tier": "agent",
                "content": "bad content",
                "version": 1,
            },
        )
        await db_session.commit()

        with patch(
            "loom.services.retrieval.providers.StubProvider.embed",
            side_effect=ValueError("compute failed"),
        ):
            with pytest.raises(ValueError, match="compute failed"):
                await process_embedding_job(unit_id, "bad content")


# ── DLQ Tests ──────────────────────────────────────────────────────────────────


class TestDLQ:
    """Dead-letter queue management utilities."""

    async def test_count_dlq(self, redis_client) -> None:
        """count_dlq returns the number of items in the DLQ."""
        from loom.services.retrieval.dlq import count_dlq

        # Seed DLQ
        await redis_client.lpush(
            "embedding:dlq",
            json.dumps({"context_unit_id": str(uuid.uuid4()), "attempt": 3, "error": "fail"}),
        )
        assert await count_dlq() == 1

    async def test_replay_dlq(self, redis_client) -> None:
        """replay_dlq atomically moves all items from DLQ to main queue."""
        from loom.services.retrieval.dlq import replay_dlq

        for i in range(3):
            await redis_client.lpush(
                "embedding:dlq",
                json.dumps({"context_unit_id": str(uuid.uuid4()), "attempt": i, "error": "x"}),
            )

        moved = await replay_dlq()
        assert moved == 3
        assert await redis_client.llen("embedding:dlq") == 0
        assert await redis_client.llen("embedding:queue") == 3

    async def test_list_dlq(self, redis_client) -> None:
        """list_dlq returns deserialized job dicts."""
        from loom.services.retrieval.dlq import list_dlq

        uid = str(uuid.uuid4())
        await redis_client.lpush(
            "embedding:dlq",
            json.dumps({"context_unit_id": uid, "attempt": 3, "error": "fail"}),
        )

        items = await list_dlq()
        assert len(items) == 1
        assert items[0]["context_unit_id"] == uid
        assert items[0]["attempt"] == 3


# ── Worker Recovery Tests ──────────────────────────────────────────────────────


class TestWorkerRecovery:
    """Orphaned in-progress job recovery."""

    async def test_recovery_requeues_inprogress(self, redis_client) -> None:
        """On startup, orphaned in-progress jobs are moved back to the queue."""
        from loom.services.retrieval.embedding_worker import recover_inprogress

        # Seed in-progress list
        await redis_client.lpush(
            "embedding:inprogress",
            json.dumps({"context_unit_id": str(uuid.uuid4()), "attempt": 0}),
        )
        await redis_client.lpush(
            "embedding:inprogress",
            json.dumps({"context_unit_id": str(uuid.uuid4()), "attempt": 1}),
        )

        await recover_inprogress()

        assert await redis_client.llen("embedding:inprogress") == 0
        assert await redis_client.llen("embedding:queue") == 2
