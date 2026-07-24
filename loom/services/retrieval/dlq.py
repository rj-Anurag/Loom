"""Dead-letter queue utilities for the embedding pipeline.

Failed jobs accumulate in ``embedding:dlq`` up to ``MAX_ATTEMPTS`` retries.
These helpers inspect and replay DLQ items.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from loom.services.retrieval.queue import DLQ_KEY, QUEUE_KEY, get_redis

logger = logging.getLogger(__name__)


async def count_dlq() -> int:
    """Return the number of items in the dead-letter queue."""
    r = get_redis()
    return await r.llen(DLQ_KEY)


async def list_dlq(limit: int = 10) -> list[dict[str, Any]]:
    """Return up to *limit* deserialised job dicts from the DLQ (most recent first)."""
    r = get_redis()
    items = await r.lrange(DLQ_KEY, 0, limit - 1)
    return [json.loads(item) for item in items]


async def replay_dlq() -> int:
    """Atomically move all items from the DLQ back to the main queue.

    Returns the number of items replayed.
    """
    r = get_redis()
    count = 0
    while True:
        item = await r.rpoplpush(DLQ_KEY, QUEUE_KEY)
        if item is None:
            break
        count += 1
    if count:
        logger.info("Replayed %d items from DLQ to embedding queue", count)
    return count
