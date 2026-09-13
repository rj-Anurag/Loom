"""Atomic abuse-limit behavior for public authentication operations."""

from unittest.mock import AsyncMock

import pytest

from loom.config import settings
from loom.services.accounts.rate_limit import RateLimitExceededError, enforce_rate_limit


async def test_rate_limit_counter_and_expiry_are_applied_atomically(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    redis = AsyncMock()
    redis.eval.return_value = settings.auth_rate_limit_attempts

    await enforce_rate_limit(redis, operation="login", identifier="User@Example.com")

    redis.eval.assert_awaited_once()
    script, key_count, key, window = redis.eval.await_args.args
    assert "INCR" in script and "EXPIRE" in script
    assert key_count == 1
    assert key.startswith("loom:rate:login:")
    assert "user@example.com" not in key
    assert window == settings.auth_rate_limit_window_seconds


async def test_rate_limit_rejects_requests_over_the_limit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    redis = AsyncMock()
    redis.eval.return_value = settings.auth_rate_limit_attempts + 1

    with pytest.raises(RateLimitExceededError):
        await enforce_rate_limit(redis, operation="login", identifier="user@example.com")
