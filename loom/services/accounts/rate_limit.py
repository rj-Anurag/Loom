"""Redis-backed fixed-window limits for public identity mutations."""

from __future__ import annotations

import hashlib

import redis.asyncio as redis_async
from redis.exceptions import RedisError

from loom.config import settings


class RateLimitExceededError(RuntimeError):
    pass


class RateLimitUnavailableError(RuntimeError):
    pass


async def enforce_rate_limit(
    redis: redis_async.Redis | None,
    *,
    operation: str,
    identifier: str,
) -> None:
    """Limit an operation while avoiding raw identifiers in Redis keys."""

    if settings.environment == "development":
        return
    if redis is None:
        raise RateLimitUnavailableError
    digest = hashlib.sha256(identifier.strip().casefold().encode("utf-8")).hexdigest()
    key = f"loom:rate:{operation}:{digest}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.auth_rate_limit_window_seconds)
    except RedisError as exc:
        raise RateLimitUnavailableError from exc
    if count > settings.auth_rate_limit_attempts:
        raise RateLimitExceededError
