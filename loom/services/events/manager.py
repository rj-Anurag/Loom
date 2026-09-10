"""In-memory WebSocket connection manager for per-project event broadcasting.

Maintains a dict of ``project_id → set[WebSocket]`` mappings.  Delivers
best-effort broadcasts: dead connections are silently removed during
broadcast iteration.

Single-server only (no Redis pub/sub).  Redis pub/sub for multi-server
deployments is deferred to a future phase.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections grouped by project_id.

    Thread-safety: asyncio single-threaded — no locks needed.
    All operations are async-safe for a single event loop.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    @property
    def active_connections(self) -> dict[str, set[WebSocket]]:
        """Read-only view of the connection dict (for testing/inspection)."""
        return dict(self._connections)

    async def connect(self, websocket: WebSocket, project_id: str) -> None:
        """Register a WebSocket for the given project.

        Must be called AFTER ``websocket.accept()`` — this method does
        not call accept itself.
        """
        self._connections[project_id].add(websocket)
        logger.info(
            "WS client connected — project=%s, total=%d",
            project_id,
            len(self._connections[project_id]),
        )

    async def disconnect(self, websocket: WebSocket, project_id: str) -> None:
        """Remove a WebSocket from the project set.

        Safe to call even if the websocket is not in the set
        (e.g. if connect was never completed).
        """
        ws_set = self._connections.get(project_id)
        if ws_set:
            ws_set.discard(websocket)
            if not ws_set:
                del self._connections[project_id]
            logger.info("WS client disconnected — project=%s", project_id)

    async def broadcast(self, project_id: str, event: dict[str, Any]) -> None:
        """Send a JSON event to all connected clients for a project.

        Best-effort delivery: failed sends log a warning and the dead
        connection is removed silently.  Never raises.
        """
        ws_set = self._connections.get(project_id)
        if not ws_set:
            return

        message = json.dumps(event)
        dead: list[WebSocket] = []

        for ws in ws_set:
            try:
                await ws.send_text(message)
            except Exception:
                logger.warning("Failed to send WS message — removing connection")
                dead.append(ws)

        for ws in dead:
            ws_set.discard(ws)

        if dead and not ws_set:
            del self._connections[project_id]


# Module-level singleton (same pattern as queue.py's Redis client)
connection_manager = ConnectionManager()


__all__ = [
    "ConnectionManager",
    "connection_manager",
]
