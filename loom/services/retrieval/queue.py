"""Redis-backed embedding job queue.

Fire-and-forget enqueue after a context write succeeds.  The worker picks
up jobs from ``embedding:queue``, processes them, and failed jobs go to
``embedding:dlq``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as redis_async

from loom.config import settings

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

QUEUE_KEY = "embedding:queue"
"""Redis LIST key for pending embedding jobs."""

INPROGRESS_KEY = "embedding:inprogress"
"""Redis LIST key for jobs currently being processed (for crash recovery)."""

DLQ_KEY = "embedding:dlq"
"""Redis LIST key for failed jobs that exceeded max attempts."""

MAX_ATTEMPTS = 3
"""Maximum number of times a job is retried before landing in the DLQ."""

MAX_CONTENT_LENGTH = 5000
"""Truncate content to this many characters in the queue payload."""

# ── Redis connection ───────────────────────────────────────────────────────────

_redis: redis_async.Redis | None = None


def get_redis() -> redis_async.Redis:
    """Lazy-init module-level Redis connection pool."""
    global _redis  # noqa: PLW0603
    if _redis is None:
        _redis = redis_async.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis


# ── Enqueue ────────────────────────────────────────────────────────────────────


async def enqueue_embedding_job(
    context_unit_id: str,
    content: str,
) -> None:
    """Push an embedding job onto the ``embedding:queue`` Redis LIST.

    Parameters
    ----------
    context_unit_id : str
        UUID of the context unit to embed.
    content : str
        The unit's text content (truncated to ``MAX_CONTENT_LENGTH``).

    Notes
    -----
    This is a fire-and-forget operation.  If Redis is unreachable the
    error is logged but **not** raised — the write already committed and
    should not be rolled back because of a downstream embedding failure.
    """
    job: dict[str, Any] = {
        "context_unit_id": context_unit_id,
        "content": content[:MAX_CONTENT_LENGTH],
        "attempt": 0,
    }
    try:
        r = get_redis()
        await r.lpush(QUEUE_KEY, json.dumps(job))
    except Exception:
        logger.exception(
            "Failed to enqueue embedding job for unit %s",
            context_unit_id,
        )
