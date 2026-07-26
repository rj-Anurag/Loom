"""WebSocket event broadcasting router.

Provides a single WebSocket endpoint:

    GET /v1/projects/{project_id}/events?token={token}

Auth is via query parameter (documented limitation — token is logged
by proxies). All events use the ``ProjectEvent`` envelope from
``loom.schemas.events``.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from loom.services.events.manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Auth Dependency ──────────────────────────────────────────────────────────


async def get_ws_agent(websocket: WebSocket, project_id: uuid.UUID, token: str = Query(...)) -> uuid.UUID | None:
    """Dependency: validate WS token and return the agent UUID.

    Closes the WebSocket with code 4001 and returns ``None`` on failure.
    Override this dependency in tests to avoid DB round-trips.
    """
    # Validate token is a UUID
    try:
        agent_id = uuid.UUID(token)
    except ValueError:
        await websocket.close(code=4001, reason="INVALID_TOKEN")
        return None

    # DB auth lookup
    from loom.db import async_session_factory
    from loom.models import Agent

    session = async_session_factory()
    try:
        agent = await session.get(Agent, agent_id)
        if agent is None:
            await websocket.close(code=4001, reason="UNKNOWN_AGENT")
            return None
        if agent.project_id != project_id:
            await websocket.close(code=4001, reason="PROJECT_MISMATCH")
            return None
    finally:
        await session.close()

    return agent_id


# ── WebSocket Endpoint ──────────────────────────────────────────────────────


@router.websocket(
    "/{project_id}/events",
    name="project_events",
)
async def project_events(
    websocket: WebSocket,
    project_id: uuid.UUID,
    agent_id: uuid.UUID | None = Depends(get_ws_agent),
) -> None:
    """WebSocket endpoint for real-time project events.

    Authentication
    --------------
    The ``token`` query parameter must be a valid agent UUID (same value
    used in the ``Authorization: Bearer <token>`` header for REST endpoints).
    If invalid, the WebSocket is closed with code 4001.

    Behaviour
    ---------
    - On connection: validates token, looks up agent, verifies project access.
    - On success: registers with ConnectionManager, starts receive loop.
    - The receive loop handles pings/pongs and detects disconnection.
    - On disconnect: unregisters from ConnectionManager.
    """
    if agent_id is None:
        return  # WebSocket was closed by dependency

    # ── Connection ─────────────────────────────────────────────────────────────
    await websocket.accept()
    await connection_manager.connect(websocket, str(project_id))

    try:
        # Receive loop: keep connection alive, detect disconnect
        while True:
            data = await websocket.receive_text()
            # Client can send "ping" — respond with "pong"
            if data.strip() == "ping":
                await websocket.send_text('{"type":"pong"}')
            # Any other message is ignored (client is receive-only for now)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected error in WS handler")
    finally:
        await connection_manager.disconnect(websocket, str(project_id))
