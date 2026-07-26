"""Unit tests for ConnectionManager (loom.services.events.manager).

Tests manage in-memory WebSocket sets, connect/disconnect lifecycle,
and broadcast delivery semantics.

Uses mock WebSocket objects to avoid Starlette dependency in service tests.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from loom.services.events.manager import ConnectionManager


@pytest.fixture
def manager() -> ConnectionManager:
    return ConnectionManager()


@pytest.fixture
def mock_ws() -> AsyncMock:
    ws = MagicMock()
    ws.send_text = AsyncMock()
    return ws


class TestConnect:
    """Connection registration."""

    async def test_connect_adds_to_project_set(
        self,
        manager: ConnectionManager,
        mock_ws: AsyncMock,
    ) -> None:
        await manager.connect(mock_ws, "proj-1")
        assert mock_ws in manager._connections["proj-1"]

    async def test_connect_multiple_clients(
        self,
        manager: ConnectionManager,
    ) -> None:
        ws1: AsyncMock = AsyncMock()
        ws2: AsyncMock = AsyncMock()
        await manager.connect(ws1, "proj-1")
        await manager.connect(ws2, "proj-1")
        assert len(manager._connections["proj-1"]) == 2

    async def test_connect_separate_projects(
        self,
        manager: ConnectionManager,
        mock_ws: AsyncMock,
    ) -> None:
        ws2: AsyncMock = AsyncMock()
        await manager.connect(mock_ws, "proj-1")
        await manager.connect(ws2, "proj-2")
        assert len(manager._connections["proj-1"]) == 1
        assert len(manager._connections["proj-2"]) == 1


class TestDisconnect:
    """Connection removal."""

    async def test_disconnect_removes_from_set(
        self,
        manager: ConnectionManager,
        mock_ws: AsyncMock,
    ) -> None:
        await manager.connect(mock_ws, "proj-1")
        await manager.disconnect(mock_ws, "proj-1")
        assert "proj-1" not in manager._connections

    async def test_disconnect_unknown_ws_is_noop(
        self,
        manager: ConnectionManager,
    ) -> None:
        await manager.disconnect(AsyncMock(), "proj-1")
        assert "proj-1" not in manager._connections

    async def test_disconnect_last_client_removes_key(
        self,
        manager: ConnectionManager,
    ) -> None:
        ws1: AsyncMock = AsyncMock()
        ws2: AsyncMock = AsyncMock()
        await manager.connect(ws1, "proj-1")
        await manager.connect(ws2, "proj-1")
        await manager.disconnect(ws1, "proj-1")
        assert "proj-1" in manager._connections
        await manager.disconnect(ws2, "proj-1")
        assert "proj-1" not in manager._connections


class TestBroadcast:
    """Event delivery."""

    async def test_broadcast_sends_to_all_clients(
        self,
        manager: ConnectionManager,
    ) -> None:
        ws1: AsyncMock = AsyncMock()
        ws2: AsyncMock = AsyncMock()
        await manager.connect(ws1, "proj-1")
        await manager.connect(ws2, "proj-1")

        event = {"type": "test", "payload": {}}
        await manager.broadcast("proj-1", event)

        expected = json.dumps(event)
        ws1.send_text.assert_awaited_once_with(expected)
        ws2.send_text.assert_awaited_once_with(expected)

    async def test_broadcast_empty_project(
        self,
        manager: ConnectionManager,
    ) -> None:
        # Should not raise
        await manager.broadcast("nonexistent", {"type": "test", "payload": {}})

    async def test_broadcast_removes_dead_connections(
        self,
        manager: ConnectionManager,
    ) -> None:
        live_ws: AsyncMock = AsyncMock()
        dead_ws: AsyncMock = AsyncMock()
        dead_ws.send_text = AsyncMock(side_effect=Exception("Connection closed"))

        await manager.connect(live_ws, "proj-1")
        await manager.connect(dead_ws, "proj-1")

        await manager.broadcast("proj-1", {"type": "test", "payload": {}})

        live_ws.send_text.assert_awaited_once()
        assert live_ws in manager._connections["proj-1"]
        assert dead_ws not in manager._connections["proj-1"]

    async def test_broadcast_no_clients(
        self,
        manager: ConnectionManager,
        mock_ws: AsyncMock,
    ) -> None:
        await manager.connect(mock_ws, "proj-1")
        await manager.disconnect(mock_ws, "proj-1")
        # Should not raise
        await manager.broadcast("proj-1", {"type": "test", "payload": {}})


class TestActiveConnections:
    """Read-only view property."""

    async def test_active_connections_returns_copy(
        self,
        manager: ConnectionManager,
        mock_ws: AsyncMock,
    ) -> None:
        await manager.connect(mock_ws, "proj-1")
        view = manager.active_connections
        assert "proj-1" in view
        assert mock_ws in view["proj-1"]
