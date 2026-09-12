"""Integration tests for the @loom CLI.

Tests CLI commands against the live API. Uses ``fastapi.testclient.TestClient``
as a sync wrapper around the ASGI app, since the CLI uses synchronous httpx calls
and ``httpx.ASGITransport`` is async-only.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from io import StringIO
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

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
            return url[len(prefix) :]
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
        """Config command prints the active local configuration."""
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
        assert "API URL" in output
        assert "API key" in output
        assert "Project ID" in output
        assert "~/.loom/projects.json" in output


class TestCLIContext:
    """`loom context` reads context captured through the API."""

    def test_write_command_is_not_registered(self) -> None:
        """Manual terminal context writes are not part of the CLI scope."""
        from loom.cli.main import build_parser

        with pytest.raises(SystemExit):
            build_parser().parse_args(["write", "manual context"])

    def test_read_context(
        self,
        sync_client: TestClient,
        test_project: Project,
        test_agent: Agent,
    ) -> None:
        """Read a context unit that was captured outside the CLI."""
        from loom.cli.main import build_parser, cmd_context

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

        seed_resp = sync_client.post(
            f"/v1/projects/{project_id}/context",
            json={
                "client_uuid": str(uuid.uuid4()),
                "type": "decision",
                "content": "Test captured context content",
                "version": 1,
            },
            headers={"Authorization": f"Bearer {agent_id}"},
        )
        assert seed_resp.status_code == 201

        # ── Read context back ────────────────────────────────────────────
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            args = parser.parse_args(["context", "captured context", "--json"])
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
        assert "Test captured context" in data["units"][0]["content"]


class TestCLIInit:
    """`loom init` creates a project and returns credentials."""

    def test_init_creates_project(self, sync_client: TestClient, tmp_path) -> None:
        """Init command calls extension/setup and prints config."""
        from loom.cli.main import build_parser, cmd_init

        old_url = os.environ.get("LOOM_API_URL")
        old_config_home = os.environ.get("LOOM_CONFIG_HOME")
        os.environ["LOOM_API_URL"] = "http://test"
        os.environ["LOOM_CONFIG_HOME"] = str(tmp_path / "loom-config")

        saved = _mock_httpx(sync_client)
        parser = build_parser()
        args = parser.parse_args(["init", "--install", "none"])

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
            if old_config_home is None:
                del os.environ["LOOM_CONFIG_HOME"]
            else:
                os.environ["LOOM_CONFIG_HOME"] = old_config_home

        output = captured.getvalue()
        assert "Project created" in output
        assert "projects.json" in output
        assert "LOOM_API_KEY" not in output
        assert (tmp_path / "loom-config" / "projects.json").is_file()

    def test_init_self_service_uses_only_loom_config(
        self,
        sync_client: TestClient,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Public init creates a project for the saved Google login."""
        from loom.api.routers import auth as auth_router
        from loom.cli.account import save_account
        from loom.cli.main import build_parser, cmd_init
        from loom.config import settings
        from loom.services.accounts.google import GoogleIdentity

        tracked = [
            "LOOM_API_URL",
            "LOOM_CONFIG_HOME",
            "LOOM_BOOTSTRAP_TOKEN",
            "LOOM_USER_TOKEN",
        ]
        original = {key: os.environ.get(key) for key in tracked}
        os.environ["LOOM_API_URL"] = "http://test"
        os.environ["LOOM_CONFIG_HOME"] = str(tmp_path / "account")
        os.environ.pop("LOOM_BOOTSTRAP_TOKEN", None)
        os.environ.pop("LOOM_USER_TOKEN", None)
        identity = GoogleIdentity(
            sub=f"cli-{uuid.uuid4()}",
            email=f"cli-{uuid.uuid4()}@example.com",
            email_verified=True,
            display_name="CLI User",
        )

        async def fake_verify(_request):
            return identity

        monkeypatch.setattr(settings, "google_oauth_enabled", True)
        monkeypatch.setattr(auth_router, "verify_google_exchange", fake_verify)
        login = sync_client.post(
            "/v1/auth/google/exchange",
            json={"client_kind": "cli", "access_token": "google-access-token"},
        ).json()
        save_account("http://test", login["session_token"])

        saved = _mock_httpx(sync_client)
        try:
            args = build_parser().parse_args(
                ["init", "Public Workspace", "--install", "none"]
            )
            cmd_init(args)
        finally:
            _restore_httpx(saved)
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        assert not (tmp_path / ".env").exists()
        assert (tmp_path / "account" / "account.json").is_file()
        project_config = json.loads(
            (tmp_path / "account" / "projects.json").read_text(encoding="utf-8")
        )
        assert project_config["current_server_url"] == "http://test"

    def test_authenticated_init_creates_project_without_writing_dotenv(
        self,
        sync_client: TestClient,
        tmp_path,
        monkeypatch,
    ) -> None:
        from loom.api.routers import auth as auth_router
        from loom.cli.account import save_account
        from loom.cli.main import build_parser, cmd_init
        from loom.config import settings
        from loom.services.accounts.google import GoogleIdentity

        identity = GoogleIdentity(
            sub=f"google-style-{uuid.uuid4()}",
            email=f"google-style-{uuid.uuid4()}@example.com",
            email_verified=True,
            display_name="Google Style User",
        )

        async def fake_verify(_request):
            return identity

        monkeypatch.setattr(settings, "google_oauth_enabled", True)
        monkeypatch.setattr(auth_router, "verify_google_exchange", fake_verify)
        login = sync_client.post(
            "/v1/auth/google/exchange",
            json={"client_kind": "cli", "access_token": "google-access-token"},
        ).json()
        tracked = ["LOOM_API_URL", "LOOM_CONFIG_HOME", "LOOM_USER_TOKEN"]
        original = {key: os.environ.get(key) for key in tracked}
        os.environ["LOOM_API_URL"] = "http://test"
        os.environ["LOOM_CONFIG_HOME"] = str(tmp_path / "loom-config")
        os.environ.pop("LOOM_USER_TOKEN", None)
        save_account("http://test", login["session_token"])

        saved = _mock_httpx(sync_client)
        try:
            args = build_parser().parse_args(
                ["init", "Terminal Project", "--install", "none"]
            )
            cmd_init(args)
        finally:
            _restore_httpx(saved)
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        assert not (tmp_path / ".env").exists()
        project_config = json.loads(
            (tmp_path / "loom-config" / "projects.json").read_text(encoding="utf-8")
        )
        projects = project_config["servers"]["http://test"]["projects"]
        assert any(project["name"] == "Terminal Project" for project in projects.values())


class TestCLIGoogleLogin:
    def test_google_login_reports_missing_server_route(self, monkeypatch) -> None:
        import httpx

        from loom.cli.oauth import OAuthLoginError, google_login

        def missing_config(url: str, **_kwargs):
            return httpx.Response(
                404,
                json={"detail": "Not Found"},
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx, "get", missing_config)

        with pytest.raises(OAuthLoginError, match="does not expose Google login"):
            google_login("http://test", timeout_seconds=1)

    def test_google_login_saves_only_account_session(self, monkeypatch, tmp_path) -> None:
        import loom.cli.main as cli

        monkeypatch.setenv("LOOM_API_URL", "https://loom.example.com")
        monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path))
        monkeypatch.setattr(
            cli,
            "google_login",
            lambda _url: {
                "session_token": "loom_session_test",
                "user": {
                    "display_name": "Ada",
                    "email": "ada@example.com",
                },
                "projects": [],
            },
        )

        args = cli.build_parser().parse_args(["login", "--install", "none"])
        cli.cmd_login(args)

        assert (tmp_path / "account.json").is_file()
        assert not (tmp_path / "projects.json").exists()

    def test_switch_command_is_available(self) -> None:
        from loom.cli.main import build_parser

        args = build_parser().parse_args(["switch", str(uuid.uuid4()), "--install", "none"])
        assert args.command == "switch"
