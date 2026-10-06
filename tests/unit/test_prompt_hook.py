"""Prompt hook delivery remains nonblocking when Loom is unavailable."""

import io
import json

import httpx

from loom.cli import prompt_hook
from loom.cli.main import build_parser, cmd_context


def test_prompt_hook_outputs_cited_context(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        prompt_hook,
        "fetch_bundle",
        lambda _prompt: {
            "brief": "Use the stored expiry [1]",
            "evidence": [
                {
                    "citation": 1,
                    "id": "unit-one",
                    "type": "decision",
                    "source_type": "browser_chat",
                    "source_url": "https://example.test/chat",
                    "occurred_at": "2026-01-01T00:00:00Z",
                    "content": "Expiry is one hour",
                }
            ],
        },
    )
    monkeypatch.setattr(
        prompt_hook.sys, "stdin", io.StringIO(json.dumps({"prompt": "login expiry"}))
    )
    prompt_hook.main()
    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "Use the stored expiry [1]" in context
    assert "Expiry is one hour" in context


def test_prompt_hook_does_not_block_when_api_fails(monkeypatch, capsys) -> None:
    def unavailable(_prompt):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(prompt_hook, "fetch_bundle", unavailable)
    monkeypatch.setattr(prompt_hook.sys, "stdin", io.StringIO(json.dumps({"prompt": "follow up"})))
    prompt_hook.main()
    assert capsys.readouterr().out == ""


def test_follow_up_prompt_fetches_its_own_bundle(monkeypatch, capsys) -> None:
    prompts = []

    def fetch(prompt):
        prompts.append(prompt)
        return {"brief": "", "evidence": []}

    monkeypatch.setattr(prompt_hook, "fetch_bundle", fetch)
    for prompt in ("Implement login", "Now update the expiry"):
        monkeypatch.setattr(prompt_hook.sys, "stdin", io.StringIO(json.dumps({"prompt": prompt})))
        prompt_hook.main()
    assert prompts == ["Implement login", "Now update the expiry"]
    assert capsys.readouterr().out == ""


def test_clean_bundle_omits_inapplicable_provenance() -> None:
    data = {
        "evidence": [
            {"source_type": "codex_cli", "source_url": None, "source_session_id": "session-one"},
            {
                "source_type": "browser_chat",
                "source_url": "https://example.test/chat",
                "source_session_id": None,
            },
        ]
    }
    cleaned = prompt_hook.clean_bundle(data)["evidence"]
    assert cleaned[0] == {"source_type": "codex_cli", "source_session_id": "session-one"}
    assert cleaned[1] == {"source_type": "browser_chat", "source_url": "https://example.test/chat"}


def test_rich_context_cli_uses_bundle_api(monkeypatch, capsys) -> None:
    monkeypatch.setattr("loom.cli.main._check_project_config", lambda: None)
    monkeypatch.setattr("loom.cli.main._api_url", lambda: "https://loom.test")
    monkeypatch.setattr("loom.cli.main._project_id", lambda: "project-one")
    monkeypatch.setattr("loom.cli.main._headers", lambda: {})
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return httpx.Response(
            200, json={"brief": "", "evidence": []}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr("loom.cli.main.httpx.post", post)
    args = build_parser().parse_args(["context", "login", "--rich"])
    cmd_context(args)
    assert calls == [
        (
            "https://loom.test/v1/projects/project-one/context/bundle",
            {"prompt": "login", "budget": 4096},
        )
    ]
    assert capsys.readouterr().out.strip() == "No relevant context found."


def test_rich_json_cli_removes_null_provenance(monkeypatch, capsys) -> None:
    monkeypatch.setattr("loom.cli.main._check_project_config", lambda: None)
    monkeypatch.setattr("loom.cli.main._api_url", lambda: "https://loom.test")
    monkeypatch.setattr("loom.cli.main._project_id", lambda: "project-one")
    monkeypatch.setattr("loom.cli.main._headers", lambda: {})

    def post(url, **_kwargs):
        return httpx.Response(
            200,
            json={
                "brief": "Relevant [1]",
                "evidence": [
                    {
                        "citation": 1,
                        "id": "unit-one",
                        "type": "message",
                        "content": "Aurora is teal",
                        "source_type": "codex_cli",
                        "source_url": None,
                        "source_session_id": "session-one",
                        "occurred_at": "2026-10-06T00:00:00Z",
                    }
                ],
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("loom.cli.main.httpx.post", post)
    args = build_parser().parse_args(["context", "Aurora", "--rich", "--json"])
    cmd_context(args)
    item = json.loads(capsys.readouterr().out)["evidence"][0]
    assert "source_url" not in item
    assert item["source_session_id"] == "session-one"
