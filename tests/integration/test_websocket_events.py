"""Integration tests for Phase 2.5c — WebSocket events.

WS auth is handled via FastAPI dependency overrides (``get_ws_agent``)
to avoid asyncpg event-loop conflicts with ``TestClient``.

Each *class* creates ONE ``TestClient`` so the asyncpg connection pool
is always on the correct event loop.  Tests needing different overrides
update ``app.dependency_overrides`` between WS connections — FastAPI
reads overrides at request time, so this works with a shared client.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket

# ── Mock auth dependencies ────────────────────────────────────────────────


async def _mock_auth_ok(
    websocket: WebSocket, project_id: uuid.UUID, token: str = "ignored"
) -> uuid.UUID | None:
    """Return a fixed agent UUID — WS 'sees' this agent as authenticated."""
    return uuid.UUID("11111111-1111-4111-8111-111111111111")


async def _mock_auth_unknown(
    websocket: WebSocket, project_id: uuid.UUID, token: str = "ignored"
) -> uuid.UUID | None:
    """Simulate 'agent not found' — close WS with 4001."""
    await websocket.close(code=4001, reason="UNKNOWN_AGENT")
    return None


async def _mock_auth_wrong_project(
    websocket: WebSocket, project_id: uuid.UUID, token: str = "ignored"
) -> uuid.UUID | None:
    """Simulate project mismatch — close WS with 4001."""
    await websocket.close(code=4001, reason="PROJECT_MISMATCH")
    return None


# ── Helpers ────────────────────────────────────────────────────────────────


def setup_project(client: TestClient) -> tuple[str, str, str]:
    """Create a project + agent via the extension setup endpoint.

    Returns (project_id, agent_id, agent_token).
    """
    resp = client.get("/v1/extension/setup")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["id"], data["agent_id"], data["api_key"]


# ═══════════════════════════════════════════════════════════════════════════
# WebSocket Auth Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestWSAuth:
    """Authentication and connection lifecycle.

    ``client`` is created once per class so the asyncpg engine pool lives
    on a single event loop across all tests.  Each test adjusts
    ``app.dependency_overrides`` before the WebSocket connect.
    """

    @classmethod
    def setup_class(cls) -> None:
        from loom.api.main import app

        cls.app = app
        cls._client_context = TestClient(app)
        cls.client = cls._client_context.__enter__()

    @classmethod
    def teardown_class(cls) -> None:
        cls._client_context.__exit__(None, None, None)

    # NOTE: do NOT call app.dependency_overrides.clear() in teardown_class()
    # because tests that don't set overrides rely on the original get_ws_agent.

    def test_ws_connection_with_valid_token(self) -> None:
        """Valid token + matching project_id → connection succeeds."""
        from loom.api.routers.events import get_ws_agent

        self.app.dependency_overrides[get_ws_agent] = _mock_auth_ok
        try:
            pid, _, _ = setup_project(self.client)
            with self.client.websocket_connect(
                f"/v1/projects/{pid}/events?token=mock-ignored",
            ) as ws:
                ws.send_text("ping")
                response = ws.receive_text()
                assert json.loads(response) == {"type": "pong"}
        finally:
            self.app.dependency_overrides.clear()

    def test_ws_connection_invalid_token(self) -> None:
        """Malformed token → connection closed.

        The ``ValueError`` from ``uuid.UUID("not-a-uuid")`` is caught by
        the ``get_ws_agent`` dependency which closes the WebSocket with
        code 4001.  The close causes ``WebSocketTestSession.__enter__``
        to raise.
        """
        pid, _, _ = setup_project(self.client)
        with pytest.raises(Exception):
            with self.client.websocket_connect(
                f"/v1/projects/{pid}/events?token=not-a-uuid",
            ):
                pass

    def test_ws_connection_wrong_project(self) -> None:
        """Agent from project A connecting to project B → closed."""
        from loom.api.routers.events import get_ws_agent

        self.app.dependency_overrides[get_ws_agent] = _mock_auth_wrong_project
        try:
            pid, _, _ = setup_project(self.client)
            other_id = uuid.uuid4()
            with pytest.raises(Exception):
                with self.client.websocket_connect(
                    f"/v1/projects/{other_id}/events?token=whatever",
                ):
                    pass
        finally:
            self.app.dependency_overrides.clear()

    def test_ws_connection_unknown_agent(self) -> None:
        """UUID that doesn't match any agent → closed."""
        from loom.api.routers.events import get_ws_agent

        self.app.dependency_overrides[get_ws_agent] = _mock_auth_unknown
        try:
            pid, _, _ = setup_project(self.client)
            with pytest.raises(Exception):
                with self.client.websocket_connect(
                    f"/v1/projects/{pid}/events?token=whatever",
                ):
                    pass
        finally:
            self.app.dependency_overrides.clear()

    def test_ws_connection_missing_token(self) -> None:
        """Missing token query param → connection closed.

        FastAPI rejects the request before the handler runs (``token`` is
        a required ``Query(...)`` param), so the WebSocket never connects.
        """
        pid, _, _ = setup_project(self.client)
        with pytest.raises(Exception):
            with self.client.websocket_connect(f"/v1/projects/{pid}/events"):
                pass


# ═══════════════════════════════════════════════════════════════════════════
# Event Emission Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEventEmission:
    """Events are broadcast to connected WebSocket clients."""

    @classmethod
    def setup_class(cls) -> None:
        from loom.api.main import app

        cls.app = app
        cls._client_context = TestClient(app)
        cls.client = cls._client_context.__enter__()

    @classmethod
    def teardown_class(cls) -> None:
        cls._client_context.__exit__(None, None, None)

    def test_context_write_emits_event(self) -> None:
        """Writing context while WS is connected emits ``context_created``."""
        from loom.api.routers.events import get_ws_agent

        self.app.dependency_overrides[get_ws_agent] = _mock_auth_ok
        try:
            pid, agent_id, token = setup_project(self.client)

            with self.client.websocket_connect(
                f"/v1/projects/{pid}/events?token=mock-ignored",
            ) as ws:
                body = {
                    "client_uuid": str(uuid.uuid4()),
                    "type": "decision",
                    "content": "WS event test content",
                    "version": 1,
                }
                resp = self.client.post(
                    f"/v1/projects/{pid}/context",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 201

                raw = ws.receive_text()
                event = json.loads(raw)
                assert event["type"] == "context_created"
                assert event["project_id"] == pid
                assert "context_unit_id" in event["payload"]
                assert event["payload"]["type"] == "decision"
                assert event["payload"]["agent_id"] == agent_id
                assert "timestamp" in event
        finally:
            self.app.dependency_overrides.clear()

    def test_heartbeat_emits_event(self) -> None:
        """Heartbeat while WS is connected emits ``agent_heartbeat``."""
        import loom.config
        import loom.services.retrieval.queue as queue_module
        from loom.api.routers.events import get_ws_agent

        original_url = loom.config.settings.redis_url
        loom.config.settings.redis_url = "redis://localhost:6379/1"
        queue_module._redis = None
        self.app.dependency_overrides[get_ws_agent] = _mock_auth_ok
        try:
            pid, agent_id, token = setup_project(self.client)

            with self.client.websocket_connect(
                f"/v1/projects/{pid}/events?token=mock-ignored",
            ) as ws:
                resp = self.client.post(
                    f"/v1/agents/{agent_id}/heartbeat",
                    json={"status": "working"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 200

                raw = ws.receive_text()
                event = json.loads(raw)
                assert event["type"] == "agent_heartbeat"
                assert event["project_id"] == pid
                assert event["payload"]["agent_id"] == agent_id
                assert event["payload"]["status"] == "working"
        finally:
            loom.config.settings.redis_url = original_url
            queue_module._redis = None
            self.app.dependency_overrides.clear()

    def test_version_conflict_emits_event(self) -> None:
        """Version conflict during context write emits ``conflict_created``."""
        from loom.api.routers.events import get_ws_agent

        self.app.dependency_overrides[get_ws_agent] = _mock_auth_ok
        try:
            pid, _, token = setup_project(self.client)

            # First write a context unit to establish a parent
            body = {
                "client_uuid": str(uuid.uuid4()),
                "type": "message",
                "content": "Original",
                "version": 1,
            }
            resp = self.client.post(
                f"/v1/projects/{pid}/context",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 201
            original_id = resp.json()["id"]

            # Connect WS, then trigger a version conflict
            with self.client.websocket_connect(
                f"/v1/projects/{pid}/events?token=mock-ignored",
            ) as ws:
                conflict_body = {
                    "client_uuid": str(uuid.uuid4()),
                    "type": "message",
                    "content": "Conflict",
                    "parent_ids": [original_id],
                    "parent_relations": ["derived_from"],
                    "version": 1,  # Should be 2 → conflict
                }
                resp = self.client.post(
                    f"/v1/projects/{pid}/context",
                    json=conflict_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 409

                raw = ws.receive_text()
                event = json.loads(raw)
                assert event["type"] == "conflict_created"
                assert event["project_id"] == pid
                assert "pending_branch_id" in event["payload"]
                assert "context_unit_id" in event["payload"]
                assert event["payload"]["conflict_type"] == "version_conflict"
        finally:
            self.app.dependency_overrides.clear()
