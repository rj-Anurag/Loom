"""Readiness checks report dependency health without raising."""

from typing import Any, cast

from loom.api.main import check_readiness


class HealthySession:
    async def execute(self, statement: object) -> None:
        return None


class HealthyRedis:
    async def ping(self) -> bool:
        return True


class BrokenRedis:
    async def ping(self) -> bool:
        raise ConnectionError("offline")


async def test_readiness_requires_database_and_redis() -> None:
    healthy = await check_readiness(
        cast(Any, HealthySession()),
        cast(Any, HealthyRedis()),
    )
    degraded = await check_readiness(
        cast(Any, HealthySession()),
        cast(Any, BrokenRedis()),
    )

    assert healthy == {"database": "ok", "redis": "ok"}
    assert degraded == {"database": "ok", "redis": "unavailable"}
