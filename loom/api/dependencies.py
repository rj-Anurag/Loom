"""Shared FastAPI dependencies for the Loom API.

Provides ``get_redis`` — a ``Depends``-compatible dependency that
reuses the existing module-level Redis singleton from the retrieval
queue module.
"""

from __future__ import annotations

import redis.asyncio as redis_async

from loom.services.retrieval.queue import get_redis as _get_queue_redis


async def get_redis() -> redis_async.Redis | None:
    """FastAPI dependency that provides a Redis client or ``None``.

    Reuses the existing module-level Redis singleton from
    ``loom.services.retrieval.queue``.  If Redis is misconfigured
    the dependency degrades gracefully by returning ``None``, which
    all presence functions handle via their ``redis=None`` paths.

    Returns
    -------
    redis_async.Redis | None
        Redis client, or ``None`` if the connection URL is not set
        or the client could not be initialised.
    """
    try:
        return _get_queue_redis()
    except Exception:
        return None


__all__ = [
    "get_redis",
]
