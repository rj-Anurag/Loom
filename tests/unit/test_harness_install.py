"""Unit tests for generated native coding-harness integrations."""

from __future__ import annotations

import json
import subprocess
from argparse import Namespace

import pytest

from loom.cli.main import cmd_install


def _args(target: str, path: str) -> Namespace:
    return Namespace(target=target, path=path, with_instructions=False)


def test_install_all_creates_project_mcp_without_markdown(tmp_path, monkeypatch) -> None:
    """Claude integration is project-local and keeps credentials out of files."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("loom.cli.main._install_codex", lambda: None)

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
    monkeypatch.setattr("loom.cli.main._install_codex", lambda: None)
    agents_file = tmp_path / "AGENTS.md"
    cmd_install(_args("codex", str(tmp_path)))
    assert not agents_file.exists()

    agents_file.write_text("# Project instructions\n")

    cmd_install(_args("codex", str(tmp_path)))

    contents = agents_file.read_text()
    assert contents == "# Project instructions\n"
    assert not (tmp_path / ".claude" / "commands" / "loom.md").exists()


def test_install_codex_manages_only_loom_instruction_block(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("loom.cli.main._install_codex", lambda: None)
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text("# Project instructions\n\nKeep this text.\n")
    args = Namespace(target="codex", path=str(tmp_path), with_instructions=True)

    cmd_install(args)
    first = agents_file.read_text()
    cmd_install(args)
    second = agents_file.read_text()

    assert first == second
    assert first.startswith("# Project instructions\n\nKeep this text.\n")
    assert first.count("<!-- loom:start -->") == 1
    assert first.count("<!-- loom:end -->") == 1
    assert "read_context" in first
    assert "write_context" in first


def test_install_codex_rejects_malformed_instruction_markers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("loom.cli.main._install_codex", lambda: None)
    agents_file = tmp_path / "AGENTS.md"
    original = "# Project\n\n<!-- loom:start -->\nbroken\n"
    agents_file.write_text(original)

    with pytest.raises(SystemExit):
        cmd_install(Namespace(target="codex", path=str(tmp_path), with_instructions=True))

    assert agents_file.read_text() == original


def test_install_codex_registers_source_provenance(tmp_path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1 if len(calls) == 1 else 0, "", "")

    monkeypatch.setattr("loom.cli.main.shutil.which", lambda _name: "/usr/bin/codex")
    monkeypatch.setattr("loom.cli.main.subprocess.run", fake_run)

    cmd_install(_args("codex", str(tmp_path)))

    assert calls[0] == ["/usr/bin/codex", "mcp", "get", "loom", "--json"]
    assert calls[1] == [
        "/usr/bin/codex",
        "mcp",
        "add",
        "loom",
        "--env",
        "LOOM_SOURCE_TYPE=codex_cli",
        "--",
        "loom",
        "mcp",
    ]


def test_install_codex_refuses_incompatible_registration(tmp_path, monkeypatch) -> None:
    registration = {
        "transport": {
            "type": "stdio",
            "command": "other-loom",
            "args": ["mcp"],
            "env": None,
        }
    }
    monkeypatch.setattr("loom.cli.main.shutil.which", lambda _name: "/usr/bin/codex")
    monkeypatch.setattr(
        "loom.cli.main.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            json.dumps(registration),
            "",
        ),
    )

    with pytest.raises(SystemExit):
        cmd_install(_args("codex", str(tmp_path)))


def test_install_codex_accepts_matching_registration(tmp_path, monkeypatch) -> None:
    registration = {
        "transport": {
            "type": "stdio",
            "command": "loom",
            "args": ["mcp"],
            "env": {"LOOM_SOURCE_TYPE": "codex_cli"},
        }
    }
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(registration), "")

    monkeypatch.setattr("loom.cli.main.shutil.which", lambda _name: "/usr/bin/codex")
    monkeypatch.setattr("loom.cli.main.subprocess.run", fake_run)

    cmd_install(_args("codex", str(tmp_path)))

    assert calls == [["/usr/bin/codex", "mcp", "get", "loom", "--json"]]


def test_install_codex_reports_missing_cli(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("loom.cli.main.shutil.which", lambda _name: None)

    with pytest.raises(SystemExit):
        cmd_install(_args("codex", str(tmp_path)))
