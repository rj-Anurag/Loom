"""Secure persistence for the CLI's revocable public-user session."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def account_path() -> Path:
    root = os.environ.get("LOOM_CONFIG_HOME")
    return Path(root).expanduser() / "account.json" if root else Path.home() / ".loom/account.json"


def load_account(api_url: str, *, path: Path | None = None) -> str:
    target = path or account_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return ""
    if data.get("api_url", "").rstrip("/") != api_url.rstrip("/"):
        return ""
    token = data.get("session_token")
    return token if isinstance(token, str) else ""


def save_account(api_url: str, session_token: str, *, path: Path | None = None) -> None:
    target = path or account_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".account-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {"api_url": api_url.rstrip("/"), "session_token": session_token},
                handle,
            )
            handle.write("\n")
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def clear_account(*, path: Path | None = None) -> None:
    target = path or account_path()
    try:
        target.unlink()
    except FileNotFoundError:
        pass
