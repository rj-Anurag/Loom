"""Protected capture queue, adapter filtering, and safe install merges."""

from __future__ import annotations

import json
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from loom.cli import capture
from loom.cli.capture_import import preview
from loom.cli.capture_install import CaptureInstallError, prepare


def _binding(root: Path) -> dict[str, str]:
    data = {
        "schema_version": 1,
        "api_url": "https://loom.test",
        "project_id": str(uuid.uuid4()),
        "project_name": "Test",
    }
    path = root / ".loom/project.json"
    path.parent.mkdir()
    path.write_text(json.dumps(data))
    return data


def test_offline_queue_and_pause(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "home"))
    binding = _binding(tmp_path)
    message = {"client_uuid": str(uuid.uuid4()), "role": "user", "content": "hello"}
    assert capture.enqueue(binding, "codex_cli", "session", message)
    assert capture.status(binding["project_id"])["pending"] == 1
    assert capture.capture_home().joinpath("capture.db").stat().st_mode & 0o077 == 0
    capture.set_paused(binding["project_id"], True)
    assert not capture.enqueue(
        binding, "codex_cli", "session", {**message, "client_uuid": str(uuid.uuid4())}
    )
    assert capture.status(binding["project_id"])["pending"] == 1
    capture.set_paused(binding["project_id"], False)
    assert capture.status(binding["project_id"])["enabled"]


def test_codex_hook_filters_tools_and_queues_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "home"))
    binding = _binding(tmp_path)
    monkeypatch.setattr(capture, "flush", lambda **_kwargs: (0, 1))
    event = {
        "cwd": str(tmp_path),
        "session_id": "session",
        "turn_id": "turn",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "A requirement",
    }
    assert capture.capture_hook("codex", event)
    assert not capture.capture_hook("codex", {**event, "agent_id": "subagent"})
    assert not capture.capture_hook("codex", {**event, "hook_event_name": "PostToolUse"})
    assert capture.status(binding["project_id"])["pending"] == 1


def test_queue_retries_and_remembers_delivery(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "home"))
    binding = _binding(tmp_path)
    monkeypatch.setenv("LOOM_PROJECT_ID", binding["project_id"])
    monkeypatch.setenv("LOOM_API_KEY", "test-key")
    message = {"client_uuid": str(uuid.uuid4()), "role": "user", "content": "retry me"}
    capture.enqueue(binding, "codex_cli", "s", message)

    def offline(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(capture.httpx, "post", offline)
    assert capture.flush() == (0, 1)
    assert capture.status(binding["project_id"])["errors"] == ["ConnectError"]

    def online(url, **_kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(capture.httpx, "post", online)
    assert capture.flush(force=True) == (1, 0)
    assert not capture.enqueue(binding, "codex_cli", "s", message)


def test_removed_session_clears_pending_uploads_and_stops_future_capture(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "home"))
    binding = _binding(tmp_path)
    monkeypatch.setenv("LOOM_PROJECT_ID", binding["project_id"])
    monkeypatch.setenv("LOOM_API_KEY", "test-key")
    first = {"client_uuid": str(uuid.uuid4()), "role": "user", "content": "remove"}
    second = {"client_uuid": str(uuid.uuid4()), "role": "assistant", "content": "later"}
    kept = {"client_uuid": str(uuid.uuid4()), "role": "user", "content": "keep"}
    assert capture.enqueue(binding, "codex_cli", "removed", first)
    assert capture.enqueue(binding, "codex_cli", "removed", second)
    assert capture.enqueue(binding, "codex_cli", "kept", kept)
    calls = []

    def response(url, **kwargs):
        calls.append(kwargs["content"])
        if b'"removed"' in kwargs["content"]:
            return httpx.Response(
                400, json={"detail": "SOURCE_REMOVED"}, request=httpx.Request("POST", url),
            )
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(capture.httpx, "post", response)
    assert capture.flush() == (1, 0)
    assert len(calls) == 2  # The second removed message was discarded locally.
    assert not capture.enqueue(
        binding, "codex_cli", "removed",
        {"client_uuid": str(uuid.uuid4()), "role": "user", "content": "future"},
    )
    assert capture.enqueue(
        binding, "codex_cli", "kept",
        {"client_uuid": str(uuid.uuid4()), "role": "user", "content": "future"},
    )


def test_legacy_queued_payload_without_source_key_still_uploads(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "home"))
    binding = _binding(tmp_path)
    monkeypatch.setenv("LOOM_PROJECT_ID", binding["project_id"])
    monkeypatch.setenv("LOOM_API_KEY", "test-key")
    with capture._connect() as connection:
        connection.execute(
            "INSERT INTO delivery (client_uuid, project_id, api_url, payload) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), binding["project_id"], binding["api_url"], '{}'),
        )

    def online(url, **_kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(capture.httpx, "post", online)
    assert capture.flush() == (1, 0)


def test_claude_repeated_prompts_have_distinct_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "home"))
    binding = _binding(tmp_path)
    monkeypatch.setattr(capture, "flush", lambda **_kwargs: (0, 1))
    event = {
        "cwd": str(tmp_path),
        "session_id": "s",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "same prompt",
    }
    assert capture.capture_hook("claude", event)
    assert capture.capture_hook("claude", event)
    assert capture.status(binding["project_id"])["pending"] == 2


def test_opencode_excludes_tool_and_reasoning_parts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "home"))
    binding = _binding(tmp_path)
    monkeypatch.setattr(capture, "flush", lambda **_kwargs: (0, 1))
    event = {
        "cwd": str(tmp_path),
        "session_id": "s",
        "messages": [
            {"id": "u1", "role": "user", "parts": [{"type": "text", "text": "Need this"}]},
            {
                "id": "a1",
                "role": "assistant",
                "finish": "stop",
                "parts": [
                    {"type": "reasoning", "text": "private"},
                    {"type": "tool", "text": "command output"},
                    {"type": "text", "text": "Done"},
                ],
            },
        ],
    }
    assert capture.capture_hook("opencode", event)
    assert capture.status(binding["project_id"])["pending"] == 2
    with capture._connect() as connection:
        payloads = [
            json.loads(row[0]) for row in connection.execute("SELECT payload FROM delivery")
        ]
    contents = [payload["messages"][0]["content"] for payload in payloads]
    assert contents == ["Need this", "Done"]


def test_codex_import_is_preview_only_and_repository_filtered(tmp_path, monkeypatch) -> None:
    binding = _binding(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    sessions = home / ".codex/sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "type": "session_meta",
            "payload": {"id": "native", "cwd": str(tmp_path), "thread_source": "user"},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-10-02T10:00:00Z",
            "payload": {"type": "user_message", "message": "Import requirement"},
        },
        {
            "type": "response_item",
            "timestamp": "2026-10-02T10:00:00Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Import requirement"}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-10-02T10:01:00Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "Accepted"}],
            },
        },
        {"type": "response_item", "payload": {"type": "function_call", "arguments": "secret"}},
    ]
    (sessions / "native.jsonl").write_text("\n".join(json.dumps(item) for item in records))
    candidates = preview("codex", binding, tmp_path)
    assert [item[2]["content"] for item in candidates] == ["Import requirement", "Accepted"]
    assert not (home / "capture.db").exists()
    assert preview("codex", binding, tmp_path, "other") == []


def test_claude_import_accepts_final_text_without_tool_results(tmp_path, monkeypatch) -> None:
    binding = _binding(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    sessions = home / ".claude/projects/repo"
    sessions.mkdir(parents=True)
    records = [
        {
            "type": "user",
            "cwd": str(tmp_path),
            "sessionId": "claude-native",
            "message": {"role": "user", "content": "Please retain this"},
        },
        {
            "type": "user",
            "cwd": str(tmp_path),
            "sessionId": "claude-native",
            "message": {"role": "user", "content": [{"type": "tool_result", "content": "secret"}]},
        },
        {
            "type": "assistant",
            "cwd": str(tmp_path),
            "sessionId": "claude-native",
            "message": {
                "role": "assistant",
                "stop_reason": "stop_sequence",
                "content": [
                    {"type": "thinking", "thinking": "private"},
                    {"type": "text", "text": "Final answer"},
                ],
            },
        },
    ]
    (sessions / "claude-native.jsonl").write_text("\n".join(json.dumps(item) for item in records))
    candidates = preview("claude", binding, tmp_path)
    assert [item[2]["content"] for item in candidates] == [
        "Please retain this",
        "Final answer",
    ]


def test_nested_repository_cannot_capture_into_parent_project(tmp_path) -> None:
    _binding(tmp_path)
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    with pytest.raises(capture.ProjectConfigError):
        capture.repository_config(nested)


def test_concurrent_hooks_do_not_lose_messages(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "home"))
    binding = _binding(tmp_path)
    messages = [
        {"client_uuid": str(uuid.uuid4()), "role": "user", "content": "text"} for _ in range(20)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(
            pool.map(
                lambda message: capture.enqueue(binding, "codex_cli", "session", message),
                messages,
            )
        )
    assert capture.status(binding["project_id"])["pending"] == 20


def test_capture_install_rejects_missing_binding_and_malformed_hooks(tmp_path) -> None:
    with pytest.raises(CaptureInstallError):
        prepare(tmp_path, {"codex"})
    _binding(tmp_path)
    target = tmp_path / ".codex/hooks.json"
    target.parent.mkdir()
    target.write_text('{"hooks":{"Stop":["bad entry"]}}')
    original = target.read_text()
    with pytest.raises(CaptureInstallError):
        prepare(tmp_path, {"codex"})
    assert target.read_text() == original


def test_capture_install_rejects_older_harness_without_writing(tmp_path, monkeypatch) -> None:
    _binding(tmp_path)
    executable = tmp_path / "codex"
    executable.touch()
    monkeypatch.setattr("loom.cli.capture_install.shutil.which", lambda _name: str(executable))
    monkeypatch.setattr(
        "loom.cli.capture_install.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "codex-cli 0.159.0", ""),
    )
    with pytest.raises(CaptureInstallError, match="0.160.0"):
        prepare(tmp_path, {"codex"})
    assert not (tmp_path / ".codex/hooks.json").exists()


def test_capture_install_preserves_unrelated_hooks(tmp_path) -> None:
    _binding(tmp_path)
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}})
    )
    prepared = prepare(tmp_path, {"codex"})
    assert len(prepared) == 1
    installed = json.loads(prepared[0][1])
    assert len(installed["hooks"]["Stop"]) == 2
    path.write_text(prepared[0][1])
    assert prepare(tmp_path, {"codex"}) == []
    path.write_text(
        path.read_text().replace("loom capture event codex", "loom capture event other")
    )
    try:
        prepare(tmp_path, {"codex"})
    except CaptureInstallError:
        pass
    else:
        raise AssertionError("conflicting Loom hook must be rejected")
