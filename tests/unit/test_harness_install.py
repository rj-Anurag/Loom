"""Unit tests for generated native coding-harness integrations."""

from __future__ import annotations

import json
import subprocess
from argparse import Namespace

import pytest

from loom.cli.main import build_parser, cmd_install


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
    assert server["env"] == {"LOOM_SOURCE_TYPE": "claude_code"}
    assert "LOOM_API_KEY" not in (tmp_path / ".mcp.json").read_text()
    assert "loom_" not in (tmp_path / ".mcp.json").read_text()

    opencode = json.loads((tmp_path / "opencode.json").read_text())
    assert opencode["mcp"]["loom"] == {
        "type": "local",
        "command": ["loom", "mcp"],
        "enabled": True,
        "environment": {"LOOM_SOURCE_TYPE": "opencode"},
    }
    assert "LOOM_API_KEY" not in (tmp_path / "opencode.json").read_text()

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


def test_install_claude_preserves_config_and_is_idempotent(tmp_path) -> None:
    config_path = tmp_path / ".mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "custom": {"keep": True},
                "mcpServers": {"other": {"command": "other", "args": []}},
            }
        )
    )

    args = _args("claude", str(tmp_path))
    cmd_install(args)
    first = config_path.read_text()
    cmd_install(args)

    assert config_path.read_text() == first
    config = json.loads(first)
    assert config["custom"] == {"keep": True}
    assert config["mcpServers"]["other"] == {"command": "other", "args": []}
    assert config["mcpServers"]["loom"]["env"] == {
        "LOOM_SOURCE_TYPE": "claude_code"
    }


def test_install_claude_refuses_conflict_unchanged(tmp_path) -> None:
    config_path = tmp_path / ".mcp.json"
    original = json.dumps({"mcpServers": {"loom": {"command": "other"}}})
    config_path.write_text(original)

    with pytest.raises(SystemExit):
        cmd_install(_args("claude", str(tmp_path)))

    assert config_path.read_text() == original


def test_install_claude_instructions_import_agents_and_preserve_content(tmp_path) -> None:
    claude_file = tmp_path / "CLAUDE.md"
    claude_file.write_text("# Existing Claude instructions\n")
    args = Namespace(
        target="claude",
        path=str(tmp_path),
        with_instructions=True,
    )

    cmd_install(args)
    first_claude = claude_file.read_text()
    first_agents = (tmp_path / "AGENTS.md").read_text()
    cmd_install(args)

    assert claude_file.read_text() == first_claude
    assert first_claude.startswith("# Existing Claude instructions\n")
    assert first_claude.count("@AGENTS.md") == 1
    assert "<!-- loom:claude:start -->" in first_claude
    assert (tmp_path / "AGENTS.md").read_text() == first_agents
    assert "read_context" in first_agents
    assert "write_context" in first_agents


def test_install_claude_leaves_existing_agents_import_unchanged(tmp_path) -> None:
    claude_file = tmp_path / "CLAUDE.md"
    original = "@AGENTS.md\n\n# Existing Claude instructions\n"
    claude_file.write_text(original)

    cmd_install(
        Namespace(target="claude", path=str(tmp_path), with_instructions=True)
    )

    assert claude_file.read_text() == original


def test_install_opencode_preserves_config_and_is_idempotent(tmp_path) -> None:
    config_path = tmp_path / "opencode.json"
    config_path.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "example/model",
                "mcp": {"other": {"type": "remote", "url": "https://example.com"}},
            }
        )
    )

    args = _args("opencode", str(tmp_path))
    cmd_install(args)
    first = config_path.read_text()
    cmd_install(args)

    assert config_path.read_text() == first
    config = json.loads(first)
    assert config["model"] == "example/model"
    assert config["mcp"]["other"]["url"] == "https://example.com"
    assert config["mcp"]["loom"]["environment"] == {
        "LOOM_SOURCE_TYPE": "opencode"
    }


def test_install_opencode_refuses_conflict_unchanged(tmp_path) -> None:
    config_path = tmp_path / "opencode.json"
    original = json.dumps({"mcp": {"loom": {"type": "remote"}}})
    config_path.write_text(original)

    with pytest.raises(SystemExit):
        cmd_install(_args("opencode", str(tmp_path)))

    assert config_path.read_text() == original


@pytest.mark.parametrize("with_json", [False, True])
def test_install_opencode_refuses_jsonc_layout_unchanged(tmp_path, with_json) -> None:
    jsonc = tmp_path / "opencode.jsonc"
    jsonc.write_text("{ // keep comments\n}\n")
    json_path = tmp_path / "opencode.json"
    if with_json:
        json_path.write_text('{"model": "keep"}\n')

    with pytest.raises(SystemExit):
        cmd_install(_args("opencode", str(tmp_path)))

    assert jsonc.read_text() == "{ // keep comments\n}\n"
    if with_json:
        assert json_path.read_text() == '{"model": "keep"}\n'
    else:
        assert not json_path.exists()


def test_install_all_preflights_local_conflicts_before_writes(tmp_path, monkeypatch) -> None:
    (tmp_path / "opencode.jsonc").write_text("{}\n")
    monkeypatch.setattr("loom.cli.main._install_codex", lambda: None)

    with pytest.raises(SystemExit):
        cmd_install(_args("all", str(tmp_path)))

    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / "opencode.json").exists()


def test_install_with_malformed_agents_markers_writes_nothing(tmp_path) -> None:
    agents_file = tmp_path / "AGENTS.md"
    original = "<!-- loom:start -->\nbroken\n"
    agents_file.write_text(original)

    with pytest.raises(SystemExit):
        cmd_install(
            Namespace(
                target="opencode",
                path=str(tmp_path),
                with_instructions=True,
            )
        )

    assert agents_file.read_text() == original
    assert not (tmp_path / "opencode.json").exists()


def test_install_with_malformed_claude_markers_writes_nothing(tmp_path) -> None:
    claude_file = tmp_path / "CLAUDE.md"
    original = "<!-- loom:claude:start -->\n@AGENTS.md\n"
    claude_file.write_text(original)

    with pytest.raises(SystemExit):
        cmd_install(
            Namespace(
                target="claude",
                path=str(tmp_path),
                with_instructions=True,
            )
        )

    assert claude_file.read_text() == original
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_install_parser_accepts_opencode_for_all_project_flows() -> None:
    parser = build_parser()
    for command in ("init", "login", "switch"):
        argv = [command]
        if command == "switch":
            argv.append("00000000-0000-0000-0000-000000000000")
        argv.extend(["--install", "opencode"])
        assert parser.parse_args(argv).install == "opencode"
    assert parser.parse_args(["install", "opencode"]).target == "opencode"
