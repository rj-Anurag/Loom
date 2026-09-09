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
