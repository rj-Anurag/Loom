"""Redis-based distributed locks for the Coordination Service.

Provides atomic lock acquire/release with TTL, multi-lock acquire with
sorted UUID ordering (deadlock prevention), exponential backoff on
contention, and graceful Redis-down fallback to optimistic concurrency.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal

import redis.asyncio as redis_async
from redis import exceptions as redis_exceptions

logger = logging.getLogger(__name__)

# ── Public types ──────────────────────────────────────────────────────────────

LOCK_KEY_PREFIX = "lock:context_unit:"
PROJECT_LOCK_KEY_PREFIX = "lock:project:"
DEFAULT_TTL = 30  # seconds
DEFAULT_RETRY_DELAY = 0.1  # seconds
DEFAULT_MAX_RETRIES = 3


@dataclass
class LockResult:
    """Result of a lock acquire attempt."""

    acquired: bool
    mode: Literal["redis", "optimistic"]
    unit_id: str = ""
    error: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _lock_key(unit_id: str) -> str:
    return f"{LOCK_KEY_PREFIX}{unit_id}"


def _project_lock_key(project_id: str) -> str:
    return f"{PROJECT_LOCK_KEY_PREFIX}{project_id}"


# ── Core lock operations ──────────────────────────────────────────────────────


async def acquire_lock(
    redis: redis_async.Redis | None,
    unit_id: str,
    agent_id: str,
    ttl: int = DEFAULT_TTL,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> LockResult:
    """Acquire a distributed lock on a context unit.

    Uses atomic ``SET NX EX`` to acquire.  Retries with backoff on
    contention.  Returns optimistic mode when Redis is unreachable.

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.  ``None`` triggers immediate optimistic fallback.
    unit_id : str
        Context-unit ID to lock.
    agent_id : str
        Agent claiming the lock.
    ttl : int
        Lock TTL in seconds (default 30).
    retry_delay : float
        Base delay between retries in seconds (default 0.1).
    max_retries : int
        Maximum retry attempts on contention (default 3).

    Returns
    -------
    LockResult
        ``acquired=True, mode="redis"`` on success,
        ``acquired=True, mode="optimistic"`` when Redis is down,
        ``acquired=False`` when another agent holds the lock.
    """
    if redis is None:
        return LockResult(acquired=True, mode="optimistic", unit_id=unit_id)

    for attempt in range(max_retries + 1):
        try:
            key = _lock_key(unit_id)
            # Atomic SET NX EX — single command, no race
            acquired = await redis.set(key, agent_id, nx=True, ex=ttl)
            if acquired:
                return LockResult(acquired=True, mode="redis", unit_id=unit_id)

            if attempt < max_retries:
                wait = retry_delay * (2**attempt)  # exponential backoff
                await asyncio.sleep(wait)
        except (ConnectionError, TimeoutError, OSError, redis_exceptions.ConnectionError, redis_exceptions.TimeoutError) as exc:
            logger.warning(
                "Redis unavailable (%s) — falling back to optimistic "
                "concurrency for unit %s",
                exc,
                unit_id,
            )
            return LockResult(
                acquired=True, mode="optimistic", unit_id=unit_id,
                error=str(exc),
            )

    return LockResult(acquired=False, mode="redis", unit_id=unit_id)


async def release_lock(
    redis: redis_async.Redis | None,
    unit_id: str,
    agent_id: str,
) -> bool:
    """Release a lock only if held by the given agent.

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.  ``None`` is a no-op (returns True).
    unit_id : str
        Context-unit ID to unlock.
    agent_id : str
        Agent claiming ownership.

    Returns
    -------
    bool
        ``True`` if released (or Redis is None), ``False`` if not held by agent.
    """
    if redis is None:
        return True

    try:
        key = _lock_key(unit_id)
        # Lua script for atomic check-and-delete
        check_and_del = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        result = await redis.eval(check_and_del, 1, key, agent_id)
        return bool(result)
    except (ConnectionError, TimeoutError, OSError, redis_async.exceptions.ConnectionError, redis_async.exceptions.TimeoutError) as exc:
        logger.warning(
            "Redis unavailable during release for unit %s — optimistic mode: %s",
            unit_id,
            exc,
        )
        return True  # optimistic: assume released


async def acquire_locks(
    redis: redis_async.Redis | None,
    unit_ids: list[str],
    agent_id: str,
    ttl: int = DEFAULT_TTL,
) -> list[LockResult]:
    """Acquire locks on multiple context units in sorted UUID order.

    Acquires locks in ascending UUID order to prevent deadlocks (lock
    ordering).  If any single acquire fails, **all** previously acquired
    locks are released (all-or-nothing semantics).

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.
    unit_ids : list[str]
        Context-unit IDs to lock.
    agent_id : str
        Agent claiming the locks.
    ttl : int
        Lock TTL in seconds.

    Returns
    -------
    list[LockResult]
        One result per input unit ID, in the **original** input order.
    """
    # Build a mapping from sorted UUID → original position
    sorted_ids = sorted(unit_ids)
    results: dict[str, LockResult] = {}

    for uid in sorted_ids:
        result = await acquire_lock(redis, uid, agent_id, ttl=ttl)
        results[uid] = result
        if not result.acquired:
            # All-or-nothing: release everything acquired so far
            for released_uid in sorted_ids:
                if released_uid in results and results[released_uid].acquired:
                    await release_lock(redis, released_uid, agent_id)
                    # Update result to reflect released state
                    results[released_uid] = LockResult(
                        acquired=False, mode="redis", unit_id=released_uid,
                    )
            # Return results in original order
            return [
                results.get(uid, LockResult(acquired=False, mode="redis", unit_id=uid))
                for uid in unit_ids
            ]

    return [results.get(uid, LockResult(acquired=True, mode="redis", unit_id=uid)) for uid in unit_ids]
