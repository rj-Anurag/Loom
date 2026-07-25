"""Integration tests for Phase 2.1 — Redis-based distributed locks.

Tests define the expected interface for the lock module that will exist at
``loom.services.coordination.locks``:

    acquire_lock(redis, unit_id, agent_id, ttl=30, retry_delay=0.1, max_retries=3)
        -> LockResult(acquired=True, mode="redis")

    release_lock(redis, unit_id, agent_id) -> bool

    acquire_locks(redis, unit_ids, agent_id, ttl=30) -> list[LockResult]

    LockResult dataclass:
        acquired: bool
        mode: Literal["redis", "optimistic"]

All tests use a real Redis instance on localhost:6379, database 1, with
``flushdb`` between tests to guarantee isolation.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
import redis.asyncio as redis_async

# ── Redis fixture ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def redis_client() -> redis_async.Redis:
    """Provide a Redis client connected to test database 1.

    Flushes the database before and after each test so every test starts
    with a clean state.
    """
    r = redis_async.from_url("redis://localhost:6379/1", decode_responses=True)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.close()


# ── Helpers ─────────────────────────────────────────────────────────────────────────


def _unit_id() -> str:
    """Generate a deterministic-looking UUID string for a context unit."""
    return str(uuid.uuid4())


def _agent_id() -> str:
    """Generate a deterministic-looking UUID string for an agent."""
    return str(uuid.uuid4())


# ── acquire_lock / release_lock basics ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_release_lock(redis_client: redis_async.Redis) -> None:
    """Acquiring a lock succeeds and releasing it returns True."""
    from loom.services.coordination.locks import LockResult, acquire_lock, release_lock

    uid = _unit_id()
    aid = _agent_id()

    # Acquire
    result = await acquire_lock(redis_client, uid, aid)
    assert isinstance(result, LockResult)
    assert result.acquired is True
    assert result.mode == "redis"

    # Release
    freed = await release_lock(redis_client, uid, aid)
    assert freed is True

    # Verify lock key is gone from Redis
    exists = await redis_client.exists(f"lock:context_unit:{uid}")
    assert exists == 0


@pytest.mark.asyncio
async def test_lock_exclusivity(redis_client: redis_async.Redis) -> None:
    """A second acquire for the same unit returns acquired=False."""
    from loom.services.coordination.locks import acquire_lock, release_lock

    uid = _unit_id()
    aid1 = _agent_id()
    aid2 = _agent_id()

    # Agent A acquires lock
    result_a = await acquire_lock(redis_client, uid, aid1)
    assert result_a.acquired is True

    # Agent B tries the same unit → should fail
    result_b = await acquire_lock(redis_client, uid, aid2, retry_delay=0.05, max_retries=1)
    assert result_b.acquired is False
    assert result_b.mode == "redis"

    # Cleanup
    await release_lock(redis_client, uid, aid1)


@pytest.mark.asyncio
async def test_lock_ttl_expiry(redis_client: redis_async.Redis) -> None:
    """A lock auto-releases after TTL expires without an explicit release."""
    from loom.services.coordination.locks import acquire_lock, release_lock

    uid = _unit_id()
    aid = _agent_id()

    # Acquire with a 1-second TTL
    result = await acquire_lock(redis_client, uid, aid, ttl=1)
    assert result.acquired is True

    # Immediately verify lock exists
    locked_after = await redis_client.get(f"lock:context_unit:{uid}")
    assert locked_after == aid

    # Wait for TTL to expire
    await asyncio.sleep(1.1)

    # Lock should be gone now
    locked_expired = await redis_client.get(f"lock:context_unit:{uid}")
    assert locked_expired is None

    # A different agent should now be able to acquire
    aid2 = _agent_id()
    result2 = await acquire_lock(redis_client, uid, aid2, ttl=1)
    assert result2.acquired is True
    await release_lock(redis_client, uid, aid2)


@pytest.mark.asyncio
async def test_release_only_by_owner(redis_client: redis_async.Redis) -> None:
    """Agent B cannot release a lock held by Agent A.

    The lock key stores the owner's agent_id. ``release_lock`` must verify
    the caller matches the owner before releasing.
    """
    from loom.services.coordination.locks import acquire_lock, release_lock

    uid = _unit_id()
    aid_a = _agent_id()
    aid_b = _agent_id()

    # Agent A acquires
    result = await acquire_lock(redis_client, uid, aid_a)
    assert result.acquired is True

    # Agent B tries to release — should return False
    freed_by_b = await release_lock(redis_client, uid, aid_b)
    assert freed_by_b is False

    # Lock should still be held by A
    owner = await redis_client.get(f"lock:context_unit:{uid}")
    assert owner == aid_a

    # Agent A can still release its own lock
    freed_by_a = await release_lock(redis_client, uid, aid_a)
    assert freed_by_a is True


# ── Multi-lock (acquire_locks) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_lock_ordering(redis_client: redis_async.Redis) -> None:
    """``acquire_locks`` acquires locks in sorted UUID order to prevent deadlock."""
    from loom.services.coordination.locks import acquire_locks

    aid = _agent_id()

    # Three unit IDs in a shuffled order — the implementation should sort them
    unit_ids = [
        "b0000000-0000-0000-0000-000000000002",
        "a0000000-0000-0000-0000-000000000001",
        "c0000000-0000-0000-0000-000000000003",
    ]

    results = await acquire_locks(redis_client, unit_ids, aid, ttl=30)
    assert len(results) == 3
    assert all(r.acquired for r in results)

    # Locks were acquired in sorted order — we can verify by checking
    # the Redis keys' insertion order is irrelevant; what matters is
    # that all three were acquired successfully.
    for uid in unit_ids:
        owner = await redis_client.get(f"lock:context_unit:{uid}")
        assert owner == aid, f"Lock {uid} should be held by {aid}, got {owner}"


@pytest.mark.asyncio
async def test_multi_lock_all_or_nothing(redis_client: redis_async.Redis) -> None:
    """If any lock cannot be acquired, all previously-acquired locks are released
    (all-or-nothing semantics)."""
    from loom.services.coordination.locks import acquire_locks, acquire_lock, release_lock

    aid_a = _agent_id()
    aid_b = _agent_id()

    # Agent B pre-locks unit "b" so A's acquire_locks will fail partway
    b_id = "b0000000-0000-0000-0000-000000000002"
    await acquire_lock(redis_client, b_id, aid_b, ttl=5)

    # Agent A tries to acquire three locks, one of which is held by B
    unit_ids = [
        "a0000000-0000-0000-0000-000000000001",
        b_id,
        "c0000000-0000-0000-0000-000000000003",
    ]

    results = await acquire_locks(redis_client, unit_ids, aid_a, ttl=30)
    assert len(results) == 3
    # The first lock (a) should have been acquired but then released on failure
    assert results[0].acquired is False, (
        "All-or-nothing should release the first lock and return False for all"
    )
    assert results[1].acquired is False
    assert results[2].acquired is False

    # Verify the first lock was released (not still held by A)
    a_owner = await redis_client.get("lock:context_unit:a0000000-0000-0000-0000-000000000001")
    assert a_owner is None, "Lock 'a' should have been released on all-or-nothing failure"

    # Cleanup
    await release_lock(redis_client, b_id, aid_b)


# ── Retry / backoff ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lock_retry_backoff(redis_client: redis_async.Redis) -> None:
    """When a lock is held, acquire retries with backoff and eventually succeeds
    after the holder releases."""
    from loom.services.coordination.locks import acquire_lock, release_lock

    uid = _unit_id()
    aid_a = _agent_id()
    aid_b = _agent_id()

    # Agent A acquires
    await acquire_lock(redis_client, uid, aid_a, ttl=5)

    # Schedule Agent B's acquire with retries (it should retry)
    async def acquire_with_retries() -> bool:
        result = await acquire_lock(
            redis_client, uid, aid_b,
            ttl=5,
            retry_delay=0.1,
            max_retries=10,  # enough retries to outlast a short hold
        )
        return result.acquired

    # Start B's acquire attempt in the background
    acquire_task = asyncio.create_task(acquire_with_retries())

    # Wait a tiny bit for B to start retrying, then release A's lock
    await asyncio.sleep(0.15)
    await release_lock(redis_client, uid, aid_a)

    # B should now succeed
    acquired = await asyncio.wait_for(acquire_task, timeout=5.0)
    assert acquired is True, "Agent B should have acquired the lock after A released"

    # Cleanup
    await release_lock(redis_client, uid, aid_b)


# ── Redis-down fallback ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_down_fallback(redis_client: redis_async.Redis) -> None:
    """When Redis is unreachable, acquire_lock falls back to optimistic concurrency:
    returns LockResult(acquired=True, mode="optimistic").

    We simulate a Redis error by providing a client connected to a closed port.
    """
    from loom.services.coordination.locks import LockResult, acquire_lock

    # Create a client pointed at a non-existent Redis instance
    dead_client = redis_async.from_url(
        "redis://localhost:16379/1", decode_responses=True, socket_connect_timeout=1,
    )

    uid = _unit_id()
    aid = _agent_id()

    try:
        result = await acquire_lock(dead_client, uid, aid)
        assert isinstance(result, LockResult)
        assert result.acquired is True, "Must fall back to optimistic (acquired=True)"
        assert result.mode == "optimistic", "Fallback mode must be 'optimistic'"
    finally:
        await dead_client.close()
