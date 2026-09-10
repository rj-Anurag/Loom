"""WebSocket event broadcasting router.

Provides a single WebSocket endpoint:

    GET /v1/projects/{project_id}/events?token={token}  (development only)

Public dashboards use authenticated HTTP polling so bearer secrets never enter
URLs or intermediary logs. All events use the ``ProjectEvent`` envelope.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.config import settings
from loom.db import get_session
from loom.security import hash_api_key
from loom.services.events.manager import connection_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Auth Dependency ──────────────────────────────────────────────────────────


async def get_ws_agent(
    websocket: WebSocket,
    project_id: uuid.UUID,
    token: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> uuid.UUID | None:
    """Dependency: validate WS token and return the agent UUID.

    Closes the WebSocket with code 4001 and returns ``None`` on failure.
    Override this dependency in tests to avoid DB round-trips.
    """
    if token is None or settings.environment != "development":
        await websocket.close(code=4001, reason="QUERY_TOKEN_DISABLED")
        return None

    # Query-token auth remains available only for local compatibility. Public
    # dashboards use authenticated HTTP polling so secrets never enter URLs.
    from loom.models import Agent

    if token.startswith("loom_"):
        agent = (
            await session.execute(
                select(Agent).where(
                    Agent.credentials_ref == hash_api_key(token),
                    Agent.revoked_at.is_(None),
                    or_(Agent.expires_at.is_(None), Agent.expires_at > datetime.now(UTC)),
                )
            )
        ).scalar_one_or_none()
    elif settings.allow_legacy_uuid_tokens:
        try:
            agent_id = uuid.UUID(token)
        except ValueError:
            await websocket.close(code=4001, reason="INVALID_TOKEN")
            return None
        agent = await session.get(Agent, agent_id)
        if agent is not None and (
            agent.revoked_at is not None
            or (agent.expires_at is not None and agent.expires_at <= datetime.now(UTC))
        ):
            agent = None
    else:
        await websocket.close(code=4001, reason="INVALID_TOKEN")
        return None
    if agent is None:
        await websocket.close(code=4001, reason="UNKNOWN_AGENT")
        return None
    agent_id = agent.id
    if agent.project_id != project_id:
        await websocket.close(code=4001, reason="PROJECT_MISMATCH")
        return None

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
    Query-token authentication is a development compatibility path only.
    Production dashboards use authenticated HTTP polling.
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
