from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | None = None) -> None:
    """Load a ``.env`` file into ``os.environ`` if it exists.

    Does not override already-set environment variables.
    """
    env_path = Path.cwd() / ".env" if path is None else Path(path)

    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if key and key not in os.environ:
            os.environ[key] = val
