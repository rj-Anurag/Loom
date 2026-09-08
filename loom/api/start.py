"""Production entrypoint that applies migrations before starting the API."""

from __future__ import annotations

import asyncio
import os

import uvicorn

from loom.config import settings
from loom.services.context.migrations.runner import apply_migrations


def main() -> None:
    asyncio.run(apply_migrations())
    uvicorn.run(
        "loom.api.main:app",
        host=os.getenv("API_HOST", settings.api_host),
        port=int(os.getenv("PORT", os.getenv("API_PORT", str(settings.api_port)))),
    )


if __name__ == "__main__":
    main()
