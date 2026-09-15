"""Tests for the public one-command Loom installer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_install_script_is_valid_bash_and_avoids_privileged_installation() -> None:
    script = ROOT / "install.sh"
    result = subprocess.run(
        ["bash", "-n", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    contents = script.read_text(encoding="utf-8")
    assert "set -euo pipefail" in contents
    assert "sudo" not in contents
    assert "pipx" in contents
    assert "git+https://github.com/rj-Anurag/Loom.git" in contents
    assert "LOOM_INSTALL_SOURCE" in contents
    assert "SCRIPT_DIRECTORY" in contents


def test_windows_installer_is_user_scoped_and_supports_local_checkout() -> None:
    contents = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "Set-StrictMode -Version Latest" in contents
    assert 'Join-Path $PSScriptRoot "pyproject.toml"' in contents
    assert "git+https://github.com/rj-Anurag/Loom.git" in contents
    assert '"pip", "install", "--user", "pipx"' in contents
    assert 'Invoke-Pipx -Arguments @("install", "--force", $Source)' in contents
    assert "Start-Process" not in contents
    assert "RunAs" not in contents


def test_install_script_invokes_pipx_without_printing_private_source(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pipx_log = tmp_path / "pipx.log"

    fake_python = fake_bin / "fake-python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)

    fake_pipx = fake_bin / "pipx"
    fake_pipx.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$PIPX_LOG"\n',
        encoding="utf-8",
    )
    fake_pipx.chmod(0o755)

    private_source = "git+https://token@example.invalid/private/loom.git"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "LOOM_PYTHON": "fake-python",
        "LOOM_INSTALL_SOURCE": private_source,
        "PIPX_LOG": str(pipx_log),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "install.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert private_source not in result.stdout
    assert pipx_log.read_text(encoding="utf-8").splitlines() == [
        f"install --force {private_source}",
        "ensurepath",
    ]


def test_install_script_uses_the_checkout_by_default(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pipx_log = tmp_path / "pipx.log"

    fake_python = fake_bin / "fake-python"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)

    fake_pipx = fake_bin / "pipx"
    fake_pipx.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$PIPX_LOG"\n',
        encoding="utf-8",
    )
    fake_pipx.chmod(0o755)

    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "LOOM_PYTHON": "fake-python",
        "PIPX_LOG": str(pipx_log),
    }
    environment.pop("LOOM_INSTALL_SOURCE", None)
    result = subprocess.run(
        ["bash", str(ROOT / "install.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert pipx_log.read_text(encoding="utf-8").splitlines() == [
        f"install --force {ROOT}",
        "ensurepath",
    ]


def test_install_script_help_has_no_side_effects(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--help"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PIPX_HOME": str(tmp_path / "pipx")},
    )

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert not (tmp_path / "pipx").exists()
