"""Unit tests for generated native coding-harness integrations."""

from __future__ import annotations

import json
from argparse import Namespace

from loom.cli.main import cmd_install


def _args(target: str, path: str) -> Namespace:
    return Namespace(target=target, path=path)


def test_install_claude_creates_project_mcp_and_exact_command(tmp_path, monkeypatch) -> None:
    """Claude integration is project-local and keeps credentials out of files."""
    monkeypatch.chdir(tmp_path)

    cmd_install(_args("claude", str(tmp_path)))

    config = json.loads((tmp_path / ".mcp.json").read_text())
    server = config["mcpServers"]["loom"]
    assert server["command"] == "loom"
    assert server["args"] == ["mcp"]
    assert server["env"]["LOOM_API_KEY"] == "${LOOM_API_KEY}"
    assert "loom_" not in (tmp_path / ".mcp.json").read_text()

    command = (tmp_path / ".claude" / "commands" / "loom.md").read_text()
    assert "$ARGUMENTS" in command
    assert "read_context" in command
    assert "write_context" in command


def test_install_codex_adds_idempotent_agent_protocol(tmp_path, monkeypatch) -> None:
    """Codex receives a durable repository instruction without global mutation."""
    monkeypatch.chdir(tmp_path)
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text("# Project instructions\n")

    cmd_install(_args("codex", str(tmp_path)))
    cmd_install(_args("codex", str(tmp_path)))

    contents = agents_file.read_text()
    assert contents.count("<!-- loom:context-protocol:start -->") == 1
    assert "loom context" in contents
    assert "loom write" in contents
