"""Database migration runner for hosted deployments.

The local shell script runs migrations through Docker Compose. Hosted
environments only have the application container, so this module applies the
same SQL files through asyncpg using DATABASE_URL.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import asyncpg

from loom.config import settings

logger = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parent


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url.removeprefix("postgresql+asyncpg://")
    return url


def migration_files() -> list[Path]:
    return [
        path
        for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
        if not path.name.endswith("_down.sql")
    ]


async def apply_migrations() -> None:
    conn = await asyncpg.connect(_asyncpg_url(settings.database_url))
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        for path in migration_files():
            already_applied = await conn.fetchval(
                "SELECT 1 FROM _migrations WHERE filename = $1",
                path.name,
            )
            if already_applied:
                continue
            logger.info("Applying migration %s", path.name)
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)",
                    path.name,
                )
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Loom database migrations.")
    parser.add_argument(
        "direction",
        nargs="?",
        choices=("up",),
        default="up",
        help="Migration direction. Only 'up' is supported for hosted deployments.",
    )
    parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(apply_migrations())


if __name__ == "__main__":
    main()
