"""Unit tests for generated native coding-harness integrations."""

from __future__ import annotations

import json
from argparse import Namespace

from loom.cli.main import cmd_install


def _args(target: str, path: str) -> Namespace:
    return Namespace(target=target, path=path)


def test_install_all_creates_project_mcp_without_markdown(tmp_path, monkeypatch) -> None:
    """Claude integration is project-local and keeps credentials out of files."""
    monkeypatch.chdir(tmp_path)

    cmd_install(_args("all", str(tmp_path)))

    config = json.loads((tmp_path / ".mcp.json").read_text())
    server = config["mcpServers"]["loom"]
    assert server["command"] == "loom"
    assert server["args"] == ["mcp"]
    assert "env" not in server
    assert "LOOM_API_KEY" not in (tmp_path / ".mcp.json").read_text()
    assert "loom_" not in (tmp_path / ".mcp.json").read_text()

    assert not (tmp_path / ".claude" / "commands" / "loom.md").exists()


def test_install_codex_does_not_modify_agent_instructions(tmp_path, monkeypatch) -> None:
    """Codex integration does not create or modify project Markdown files."""
    monkeypatch.chdir(tmp_path)
    agents_file = tmp_path / "AGENTS.md"
    cmd_install(_args("codex", str(tmp_path)))
    assert not agents_file.exists()

    agents_file.write_text("# Project instructions\n")

    cmd_install(_args("codex", str(tmp_path)))

    contents = agents_file.read_text()
    assert contents == "# Project instructions\n"
    assert not (tmp_path / ".claude" / "commands" / "loom.md").exists()
