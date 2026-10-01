"""CLI tests for read-only project-memory inspection."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import httpx
import pytest

from loom.cli.main import build_parser, cmd_history, cmd_links, cmd_status
from loom.cli.project_config import ProjectConfigError, ResolvedProjectConfig

PROJECT_ID = "11111111-1111-1111-1111-111111111111"


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    config = ResolvedProjectConfig(
        api_url="https://loom.example",
        project_id=PROJECT_ID,
        project_name="Bound project",
        api_key="secret-project-key",
        source="repository",
        descriptor_path=Path(".loom/project.json"),
    )
    monkeypatch.setattr("loom.cli.main.resolve_project_config", lambda: config)


def _response(method: str, url: str, payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request(method, url),
    )


def test_inspection_parser_contract() -> None:
    parser = build_parser()

    assert parser.parse_args(["status", "--json"]).json is True
    assert parser.parse_args(["links", "--json"]).json is True
    history = parser.parse_args(
        [
            "history",
            "--limit",
            "25",
            "--source",
            "opencode",
            "--session",
            "session-one",
            "--type",
            "task_result",
            "--json",
        ]
    )
    assert history.limit == 25
    assert history.source == "opencode"
    assert history.session == "session-one"
    assert history.type == "task_result"


def test_status_json_reports_project_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(monkeypatch)

    def fake_get(url: str, **_kwargs) -> httpx.Response:
        if url.endswith("/context/sources"):
            return _response("GET", url, {"sources": [
                {"source_type": "opencode", "source_session_id": "session-one"},
                {"source_type": "mcp_agent", "source_session_id": None},
            ]})
        return _response("GET", url, {
            "id": PROJECT_ID,
            "name": "Inspection Project",
            "context_unit_count": 12,
            "linked_chat_count": 2,
        })

    monkeypatch.setattr("loom.cli.main.httpx.get", fake_get)
    cmd_status(Namespace(json=True))

    output = capsys.readouterr().out
    data = json.loads(output)
    assert data["project_name"] == "Inspection Project"
    assert data["observed_session_count"] == 1
    assert data["selection_source"] == "repository"
    assert "secret-project-key" not in output


def test_links_matches_browser_counts_and_keeps_unscoped_sources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(monkeypatch)

    def fake_get(url: str, **_kwargs) -> httpx.Response:
        if url.endswith("/chats"):
            return _response("GET", url, [{
                "id": "chat-one",
                "chat_url": "https://chatgpt.com/c/example/",
                "title": "Example",
                "platform": "chatgpt.com",
                "linked_at": "2026-10-01T10:00:00+00:00",
            }])
        return _response("GET", url, {"sources": [
            {
                "source_type": "browser_chat",
                "source_session_id": None,
                "source_url": "https://chatgpt.com/c/example",
                "agent_id": "browser-agent",
                "agent_name": "Chrome",
                "unit_count": 4,
                "first_seen_at": "2026-10-01T10:00:00+00:00",
                "last_seen_at": "2026-10-01T11:00:00+00:00",
            },
            {
                "source_type": "mcp_agent",
                "source_session_id": None,
                "source_url": None,
                "agent_id": "local-agent",
                "agent_name": "Legacy agent",
                "unit_count": 1,
                "first_seen_at": "2026-10-01T10:00:00+00:00",
                "last_seen_at": "2026-10-01T11:00:00+00:00",
            },
        ]})

    monkeypatch.setattr("loom.cli.main.httpx.get", fake_get)
    cmd_links(Namespace(json=True))

    data = json.loads(capsys.readouterr().out)
    assert data["chats"][0]["captured_unit_count"] == 4
    assert data["sessions"][0]["source_session_id"] is None


def test_history_passes_filters_and_prints_full_provenance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(monkeypatch)
    captured_params: dict[str, object] = {}

    def fake_get(url: str, **kwargs) -> httpx.Response:
        captured_params.update(kwargs["params"])
        return _response("GET", url, {
            "units": [{
                "id": "unit-full-id",
                "type": "task_result",
                "content": "Verified result",
                "source_type": "opencode",
                "source_session_id": "session-one",
                "agent_id": "agent-one",
                "agent_name": "OpenCode",
                "created_at": "2026-10-01T12:00:00+00:00",
                "parent_ids": ["parent-full-id"],
                "metadata": {"task_name": "Inspect"},
            }],
            "next_cursor": "cursor-two",
            "has_more": True,
        })

    monkeypatch.setattr("loom.cli.main.httpx.get", fake_get)
    cmd_history(Namespace(
        limit=10,
        cursor=None,
        source="opencode",
        session="session-one",
        type="task_result",
        json=False,
    ))

    output = capsys.readouterr().out
    assert captured_params == {
        "limit": 10,
        "source_type": "opencode",
        "source_session_id": "session-one",
        "type": "task_result",
    }
    assert "unit-full-id" in output
    assert "parent-full-id" in output
    assert "Verified result" in output
    assert "Next cursor: cursor-two" in output


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "Authentication failed"),
        (403, "cannot access"),
        (404, "was not found"),
    ],
)
def test_status_reports_actionable_http_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    expected: str,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(
        "loom.cli.main.httpx.get",
        lambda url, **_kwargs: _response("GET", url, {"detail": "failure"}, status),
    )

    with pytest.raises(SystemExit):
        cmd_status(Namespace(json=False))
    assert expected in capsys.readouterr().err


def test_status_reports_unavailable_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(monkeypatch)

    def unavailable(url: str, **_kwargs) -> httpx.Response:
        raise httpx.ConnectError("offline", request=httpx.Request("GET", url))

    monkeypatch.setattr("loom.cli.main.httpx.get", unavailable)
    with pytest.raises(SystemExit):
        cmd_status(Namespace(json=False))
    error = capsys.readouterr().err
    assert "Loom API is unavailable" in error
    assert "secret-project-key" not in error


def test_status_reports_missing_project_configuration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def missing() -> ResolvedProjectConfig:
        raise ProjectConfigError("No repository credential")

    monkeypatch.setattr("loom.cli.main.resolve_project_config", missing)
    with pytest.raises(SystemExit):
        cmd_status(Namespace(json=False))
    assert "No repository credential" in capsys.readouterr().err
