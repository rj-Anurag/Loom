"""Unit tests for Phase 2.4 — Redis Live Presence.

Tests the pure service functions in
``loom.services.coordination.presence`` using the ``redis_client``
fixture (real Redis on DB 1, flushed between tests).
"""

from __future__ import annotations

import redis.asyncio as redis_async

from loom.services.coordination.presence import (
    PRESENCE_KEY_PREFIX,
    get_active_agents,
    get_agent_presence,
    record_heartbeat,
)


class TestRecordHeartbeat:
    """Tests for record_heartbeat."""

    async def test_records_presence(self, redis_client: redis_async.Redis) -> None:
        """Heartbeat stores project_id, status, and optional task_id."""
        result = await record_heartbeat(
            redis_client,
            "agent-1",
            "proj-a",
            "working",
            task_id="task-42",
        )
        assert result is True

        data = await redis_client.hgetall(f"{PRESENCE_KEY_PREFIX}agent-1")
        assert data["project_id"] == "proj-a"
        assert data["status"] == "working"
        assert data["task_id"] == "task-42"

    async def test_sets_ttl(self, redis_client: redis_async.Redis) -> None:
        """Heartbeat sets a TTL on the key."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "idle")
        ttl = await redis_client.ttl(f"{PRESENCE_KEY_PREFIX}agent-1")
        assert 0 < ttl <= 60  # within HEARTBEAT_TTL

    async def test_updates_existing(self, redis_client: redis_async.Redis) -> None:
        """A second heartbeat updates the existing hash and refreshes TTL."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "working")
        await record_heartbeat(redis_client, "agent-1", "proj-a", "idle")
        data = await redis_client.hgetall(f"{PRESENCE_KEY_PREFIX}agent-1")
        assert data["status"] == "idle"

    async def test_redis_none_is_noop(self) -> None:
        """redis=None returns False without error."""
        result = await record_heartbeat(None, "agent-1", "proj-a", "working")
        assert result is False

    async def test_without_task_id(self, redis_client: redis_async.Redis) -> None:
        """Heartbeat without task_id does not store a task_id field."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "blocked")
        data = await redis_client.hgetall(f"{PRESENCE_KEY_PREFIX}agent-1")
        assert "task_id" not in data


class TestGetActiveAgents:
    """Tests for get_active_agents."""

    async def test_returns_matching_project(
        self,
        redis_client: redis_async.Redis,
    ) -> None:
        """Only agents in the requested project are returned."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "working")
        await record_heartbeat(redis_client, "agent-2", "proj-a", "idle")
        await record_heartbeat(redis_client, "agent-3", "proj-b", "working")

        agents = await get_active_agents(redis_client, "proj-a")
        assert len(agents) == 2
        agent_ids = {a["agent_id"] for a in agents}
        assert agent_ids == {"agent-1", "agent-2"}

    async def test_empty_when_no_matches(
        self,
        redis_client: redis_async.Redis,
    ) -> None:
        """Project with no agents returns empty list."""
        agents = await get_active_agents(redis_client, "proj-none")
        assert agents == []

    async def test_redis_none_returns_empty(self) -> None:
        """redis=None returns empty list."""
        agents = await get_active_agents(None, "proj-a")
        assert agents == []

    async def test_includes_all_fields(
        self,
        redis_client: redis_async.Redis,
    ) -> None:
        """Each agent dict has agent_id, project_id, status, task_id."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "blocked", task_id="t1")
        agents = await get_active_agents(redis_client, "proj-a")
        assert len(agents) == 1
        entry = agents[0]
        assert entry["agent_id"] == "agent-1"
        assert entry["project_id"] == "proj-a"
        assert entry["status"] == "blocked"
        assert entry["task_id"] == "t1"


class TestGetAgentPresence:
    """Tests for get_agent_presence."""

    async def test_returns_presence_for_active_agent(
        self,
        redis_client: redis_async.Redis,
    ) -> None:
        """Returns presence dict for an agent with a heartbeat."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "working")
        presence = await get_agent_presence(redis_client, "agent-1")
        assert presence is not None
        assert presence["agent_id"] == "agent-1"
        assert presence["status"] == "working"
        assert presence["project_id"] == "proj-a"

    async def test_returns_none_for_unknown_agent(
        self,
        redis_client: redis_async.Redis,
    ) -> None:
        """Non-existent agent returns None."""
        presence = await get_agent_presence(redis_client, "ghost-agent")
        assert presence is None

    async def test_redis_none_returns_none(self) -> None:
        """redis=None returns None."""
        presence = await get_agent_presence(None, "agent-1")
        assert presence is None

    async def test_expired_agent_returns_none(
        self,
        redis_client: redis_async.Redis,
    ) -> None:
        """After TTL expiry, agent presence returns None."""
        await record_heartbeat(redis_client, "agent-1", "proj-a", "working")
        await redis_client.expire(f"{PRESENCE_KEY_PREFIX}agent-1", 0)  # force expire
        presence = await get_agent_presence(redis_client, "agent-1")
        assert presence is None
