"""Tests for secure user-session persistence used by CLI onboarding."""

import stat
from pathlib import Path

from loom.cli.account import clear_account, load_account, save_account


def test_account_session_round_trip_uses_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "loom" / "account.json"
    save_account("https://loom.example", "loom_session_secret", path=path)

    assert load_account("https://loom.example", path=path) == "loom_session_secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    clear_account(path=path)
    assert load_account("https://loom.example", path=path) == ""


def test_account_session_is_scoped_to_server(tmp_path: Path) -> None:
    path = tmp_path / "account.json"
    save_account("https://one.example", "loom_session_secret", path=path)

    assert load_account("https://two.example", path=path) == ""
