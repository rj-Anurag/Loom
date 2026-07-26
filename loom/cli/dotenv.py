from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | None = None) -> None:
    """Load a ``.env`` file into ``os.environ`` if it exists.

    Does not override already-set environment variables.
    """
    if path is None:
        path = Path.cwd() / ".env"
    else:
        path = Path(path)

    if not path.exists():
        return

    for line in path.read_text().splitlines():
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
