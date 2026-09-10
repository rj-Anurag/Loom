"""Redis-based agent presence tracking.

Provides heartbeat recording, active-agent queries, and single-agent
presence lookup using Redis hashes with TTL-based expiry.

Graceful degradation: all public functions accept ``redis=None`` and
return a safe default (``False``, ``[]``, or ``None``).
"""

from __future__ import annotations

import logging

import redis.asyncio as redis_async
from redis import exceptions as redis_exceptions

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

PRESENCE_KEY_PREFIX = "presence:agent:"
"""Redis key prefix for agent presence hashes."""

HEARTBEAT_TTL = 60
"""TTL in seconds for heartbeat keys.  Agents without a heartbeat within
this window are considered offline."""

SCAN_COUNT = 100
"""Batch size for SCAN iteration."""


def _text(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value or ""


# ── Public API ─────────────────────────────────────────────────────────────────


async def record_heartbeat(
    redis: redis_async.Redis | None,
    agent_id: str,
    project_id: str,
    status: str,
    task_id: str | None = None,
) -> bool:
    """Record or refresh an agent heartbeat in Redis.

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.  ``None`` → no-op (returns ``False``).
    agent_id : str
        Unique agent identifier (stringified UUID).
    project_id : str
        Project the agent belongs to.
    status : str
        One of ``"idle"``, ``"working"``, ``"blocked"``.
    task_id : str | None
        Optional task UUID the agent is currently working on.

    Returns
    -------
    bool
        ``True`` if heartbeat was recorded, ``False`` if Redis was
        unavailable.

    Notes
    -----
    Uses ``HSET`` + ``EXPIRE``.  The TTL serves as the offline timeout —
    if an agent stops sending heartbeats, the key auto-expires.
    """
    if redis is None:
        return False

    key = f"{PRESENCE_KEY_PREFIX}{agent_id}"
    try:
        mapping: dict[str, str] = {
            "project_id": project_id,
            "status": status,
        }
        if task_id is not None:
            mapping["task_id"] = task_id

        async with redis.pipeline() as pipe:
            pipe.hset(key, mapping=mapping)  # type: ignore[arg-type]
            pipe.expire(key, HEARTBEAT_TTL)
            await pipe.execute()
        return True
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        redis_exceptions.ConnectionError,
        redis_exceptions.TimeoutError,
    ):
        logger.warning(
            "Redis unavailable — heartbeat not recorded for agent %s", agent_id
        )
        return False


async def get_active_agents(
    redis: redis_async.Redis | None,
    project_id: str,
) -> list[dict[str, str]]:
    """Get all active agents in a project.

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.  ``None`` → returns empty list.
    project_id : str
        Project to filter by.

    Returns
    -------
    list[dict[str, str]]
        Each dict has keys: ``agent_id``, ``project_id``, ``status``,
        ``task_id`` (may be empty string).  Items without a matching
        ``project_id`` are filtered out.

    Notes
    -----
    Uses ``SCAN`` to iterate keys (not ``KEYS`` — avoids blocking Redis).
    Batch size is ``SCAN_COUNT`` (100).  Degrades gracefully to empty
    list when Redis is unreachable.
    """
    if redis is None:
        return []

    agents: list[dict[str, str]] = []
    cursor = 0
    try:
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=f"{PRESENCE_KEY_PREFIX}*",
                count=SCAN_COUNT,
            )
            if keys:
                pipe = redis.pipeline()
                for key in keys:
                    pipe.hgetall(key)
                results = await pipe.execute()

                for key, data in zip(keys, results):
                    if data and _text(data.get("project_id")) == project_id:
                        agent_id = _text(key)[len(PRESENCE_KEY_PREFIX) :]
                        entry: dict[str, str] = {
                            "agent_id": agent_id,
                            "project_id": _text(data.get("project_id")),
                            "status": _text(data.get("status")),
                            "task_id": _text(data.get("task_id")),
                        }
                        agents.append(entry)

            if cursor == 0:
                break

        return agents
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        redis_exceptions.ConnectionError,
        redis_exceptions.TimeoutError,
    ):
        logger.warning(
            "Redis unavailable — returning empty active agents list"
        )
        return []


async def get_agent_presence(
    redis: redis_async.Redis | None,
    agent_id: str,
) -> dict[str, str] | None:
    """Get the presence data for a single agent.

    Parameters
    ----------
    redis : redis_async.Redis | None
        Redis client.  ``None`` → returns ``None``.
    agent_id : str
        Unique agent identifier.

    Returns
    -------
    dict[str, str] | None
        Presence data dict with keys ``agent_id``, ``project_id``,
        ``status``, ``task_id``, or ``None`` if the agent has no
        heartbeat record or Redis is down.
    """
    if redis is None:
        return None

    key = f"{PRESENCE_KEY_PREFIX}{agent_id}"
    try:
        data = await redis.hgetall(key)
        if not data:
            return None
        return {
            "agent_id": agent_id,
            "project_id": _text(data.get("project_id")),
            "status": _text(data.get("status")),
            "task_id": _text(data.get("task_id")),
        }
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        redis_exceptions.ConnectionError,
        redis_exceptions.TimeoutError,
    ):
        logger.warning(
            "Redis unavailable — could not fetch presence for agent %s",
            agent_id,
        )
        return None


__all__ = [
    "record_heartbeat",
    "get_active_agents",
    "get_agent_presence",
    "PRESENCE_KEY_PREFIX",
    "HEARTBEAT_TTL",
]
