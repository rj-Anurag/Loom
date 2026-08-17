"""Integration tests for the @loom CLI.

Tests CLI commands against the live API. Uses ``starlette.testclient.TestClient``
as a sync wrapper around the ASGI app, since the CLI uses synchronous httpx calls
and ``httpx.ASGITransport`` is async-only.
"""

from __future__ import annotations

import json
import os
import sys
from io import StringIO
from typing import Any

import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from loom.models import Agent, Project


# ── Test Client Fixture ───────────────────────────────────────────────────────


@pytest.fixture
def sync_client() -> TestClient:
    """Sync test client wrapping the ASGI app."""
    from loom.api.main import app

    return TestClient(app)


# ── `httpx` mock — routes sync HTTP calls through TestClient ─────────────────


def _mock_httpx(sync_client: TestClient) -> dict[str, Any]:
    """Replace httpx.get/post with versions routed through TestClient.

    Returns a dict of ``{"old_get": ..., "old_post": ...}`` for cleanup.
    """
    import httpx

    old_get = httpx.get
    old_post = httpx.post

    def mock_get(url: str, **kwargs):
        # Strip base URL to get path
        path = _strip_url(url)
        resp = sync_client.get(path, params=kwargs.get("params"), headers=kwargs.get("headers"))
        return _to_httpx_response(resp)

    def mock_post(url: str, **kwargs):
        path = _strip_url(url)
        resp = sync_client.post(path, json=kwargs.get("json"), headers=kwargs.get("headers"))
        return _to_httpx_response(resp)

    httpx.get = mock_get
    httpx.post = mock_post
    return {"old_get": old_get, "old_post": old_post}


def _strip_url(url: str) -> str:
    """Strip ``http://test`` base URL to get a relative path."""
    for prefix in ["http://test", "http://localhost:8000"]:
        if url.startswith(prefix):
            return url[len(prefix):]
    # Already a path
    return url


def _to_httpx_response(resp, request: Any = None) -> Any:
    """Convert a starlette TestClient response to an httpx Response-like object."""
    import httpx

    r = httpx.Response(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        content=resp.content,
    )
    # httpx.Response.raise_for_status() checks _request; set a stub so
    # the CLI's error handling (resp.raise_for_status()) works correctly.
    r._request = request or httpx.Request("GET", "http://test/")
    return r


def _restore_httpx(saved: dict[str, Any]) -> None:
    """Restore original httpx.get/post."""
    import httpx

    httpx.get = saved["old_get"]
    httpx.post = saved["old_post"]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_project(db_session) -> Project:
    p = Project(name="CLI Test Project")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def test_agent(db_session, test_project) -> Agent:
    a = Agent(project_id=test_project.id, kind="local", name="CLI Test Agent")
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    return a


# ═════════════════════════════════════════════════════════════════════════════
# CLI Command Tests
# ═════════════════════════════════════════════════════════════════════════════


class TestCLIConfig:
    """`loom config` displays the current configuration."""

    def test_config_shows_defaults(self) -> None:
        """Config command prints env vars with default values."""
        from loom.cli.main import build_parser, cmd_config

        parser = build_parser()
        args = parser.parse_args(["config"])

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            cmd_config(args)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "LOOM_API_URL" in output
        assert "LOOM_API_KEY" in output
        assert "LOOM_PROJECT_ID" in output


class TestCLIWriteAndContext:
    """`loom write` and `loom context` read/write through the API."""

    def test_write_and_read_context(
        self,
        sync_client: TestClient,
        test_project: Project,
        test_agent: Agent,
    ) -> None:
        """Write a context unit, then read it back."""
        from loom.cli.main import build_parser, cmd_context, cmd_write

        agent_id = str(test_agent.id)
        project_id = str(test_project.id)

        # Set env vars for the CLI
        old_key = os.environ.get("LOOM_API_KEY")
        old_pid = os.environ.get("LOOM_PROJECT_ID")
        old_url = os.environ.get("LOOM_API_URL")
        os.environ["LOOM_API_KEY"] = agent_id
        os.environ["LOOM_PROJECT_ID"] = project_id
        os.environ["LOOM_API_URL"] = "http://test"

        saved = _mock_httpx(sync_client)
        parser = build_parser()

        # ── Write a context unit ──────────────────────────────────────────
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            args = parser.parse_args(["write", "Test CLI write content", "--type", "decision"])
            cmd_write(args)
        finally:
            sys.stdout = old_stdout

        write_output = captured.getvalue()
        assert "Context unit" in write_output
        assert "created" in write_output

        # ── Read context back ────────────────────────────────────────────
        captured = StringIO()
        sys.stdout = captured
        try:
            args = parser.parse_args(["context", "CLI test", "--json"])
            cmd_context(args)
        finally:
            sys.stdout = old_stdout
            _restore_httpx(saved)
            # Restore env vars
            if old_key is None:
                del os.environ["LOOM_API_KEY"]
            else:
                os.environ["LOOM_API_KEY"] = old_key
            if old_pid is None:
                del os.environ["LOOM_PROJECT_ID"]
            else:
                os.environ["LOOM_PROJECT_ID"] = old_pid
            if old_url is None:
                del os.environ["LOOM_API_URL"]
            else:
                os.environ["LOOM_API_URL"] = old_url

        context_output = captured.getvalue()
        data = json.loads(context_output)
        assert "units" in data
        assert len(data["units"]) > 0
        assert "Test CLI write" in data["units"][0]["content"]

    def test_write_pipes_from_stdin(
        self,
        sync_client: TestClient,
        test_project: Project,
        test_agent: Agent,
    ) -> None:
        """Write command reads content from stdin when no argument given."""
        from loom.cli.main import build_parser, cmd_write

        old_key = os.environ.get("LOOM_API_KEY")
        old_pid = os.environ.get("LOOM_PROJECT_ID")
        old_url = os.environ.get("LOOM_API_URL")
        os.environ["LOOM_API_KEY"] = str(test_agent.id)
        os.environ["LOOM_PROJECT_ID"] = str(test_project.id)
        os.environ["LOOM_API_URL"] = "http://test"

        saved = _mock_httpx(sync_client)
        parser = build_parser()

        captured = StringIO()
        old_stdout = sys.stdout
        old_stdin = sys.stdin
        sys.stdin = StringIO("stdin content test\n")
        sys.stdout = captured
        try:
            # --version 2 since version 1 was used by the previous test
            args = parser.parse_args(["write", "--type", "decision", "--version", "2"])
            cmd_write(args)
        finally:
            sys.stdout = old_stdout
            sys.stdin = old_stdin
            _restore_httpx(saved)
            if old_key is None:
                del os.environ["LOOM_API_KEY"]
            else:
                os.environ["LOOM_API_KEY"] = old_key
            if old_pid is None:
                del os.environ["LOOM_PROJECT_ID"]
            else:
                os.environ["LOOM_PROJECT_ID"] = old_pid
            if old_url is None:
                del os.environ["LOOM_API_URL"]
            else:
                os.environ["LOOM_API_URL"] = old_url

        output = captured.getvalue()
        assert "Context unit" in output
        assert "created" in output


class TestCLIInit:
    """`loom init` creates a project and returns credentials."""

    def test_init_creates_project(self, sync_client: TestClient) -> None:
        """Init command calls extension/setup and prints config."""
        from loom.cli.main import build_parser, cmd_init

        old_url = os.environ.get("LOOM_API_URL")
        os.environ["LOOM_API_URL"] = "http://test"

        saved = _mock_httpx(sync_client)
        parser = build_parser()
        args = parser.parse_args(["init"])

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            cmd_init(args)
        finally:
            sys.stdout = old_stdout
            _restore_httpx(saved)
            if old_url is None:
                del os.environ["LOOM_API_URL"]
            else:
                os.environ["LOOM_API_URL"] = old_url

        output = captured.getvalue()
        assert "Project created" in output
        assert "LOOM_API_URL" in output
        assert "LOOM_API_KEY" in output
        assert "LOOM_PROJECT_ID" in output
