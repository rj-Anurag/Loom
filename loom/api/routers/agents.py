"""Agent management REST router.

Phase 2.4 — Redis Live Presence.
Provides:
- POST /v1/agents/{agent_id}/heartbeat — record agent heartbeat
- GET /v1/projects/{project_id}/agents/presence — get active agents
- POST /v1/projects/{project_id}/agents — register a new agent (Phase 1)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import redis.asyncio as redis_async

from loom.api.auth import AuthContext, require_auth
from loom.api.dependencies import get_redis
from loom.schemas.events import ProjectEvent
from loom.services.coordination.presence import (
    get_active_agents,
    record_heartbeat,
)
from loom.services.events.manager import connection_manager

router = APIRouter()


# ── Request / Response Models ────────────────────────────────────────────────


class HeartbeatRequest(BaseModel):
    """JSON body for POST /v1/agents/{agent_id}/heartbeat."""

    status: Literal["idle", "working", "blocked"] = Field(
        ...,
        description="Current agent status.",
    )
    task_id: str | None = Field(
        None,
        description="Optional task UUID the agent is working on.",
    )


# ── Heartbeat ────────────────────────────────────────────────────────────────


@router.post(
    "/agents/{agent_id}/heartbeat",
    responses={
        200: {"description": "Heartbeat recorded"},
        401: {"description": "Missing or invalid auth"},
        403: {"description": "Agent ID mismatch"},
    },
)
async def agent_heartbeat(
    agent_id: uuid.UUID,
    body: HeartbeatRequest,
    auth: AuthContext = Depends(require_auth),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> dict[str, Any]:
    """Record an agent heartbeat.

    The authenticated agent must match the ``agent_id`` path parameter.
    Heartbeat refreshes the agent's presence TTL in Redis.
    """
    # Verify agent_id matches auth
    if auth.agent_id != agent_id:
        raise HTTPException(
            status_code=403,
            detail="AGENT_ID_MISMATCH",
        )

    recorded = await record_heartbeat(
        redis=redis,
        agent_id=str(agent_id),
        project_id=str(auth.project_id) if auth.project_id else "",
        status=body.status,
        task_id=body.task_id,
    )

    # ── Fire-and-forget broadcast ────────────────────────────────────────
    if recorded and auth.project_id:
        event = ProjectEvent(
            type="agent_heartbeat",
            project_id=str(auth.project_id),
            payload={
                "agent_id": str(agent_id),
                "status": body.status,
                "task_id": body.task_id,
            },
            timestamp=datetime.now(timezone.utc).isoformat(),
        ).model_dump()
        asyncio.create_task(
            connection_manager.broadcast(str(auth.project_id), event)
        )

    return {
        "status": "ok",
        "redis_available": recorded,
    }


# ── Presence Query ───────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/agents/presence",
    responses={
        200: {"description": "Active agents list"},
        401: {"description": "Missing or invalid auth"},
        403: {"description": "Agent does not belong to this project"},
    },
)
async def get_project_agents_presence(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> list[dict[str, str]]:
    """Get all active agents in a project.

    Returns presence data (status, task_id) for each agent that has
    sent a heartbeat within the TTL window.
    """
    # Cross-project access check: the authenticated agent must belong
    # to the requested project.
    if auth.project_id is not None and auth.project_id != project_id:
        raise HTTPException(
            status_code=403,
            detail="PROJECT_MISMATCH",
        )
    return await get_active_agents(redis, str(project_id))


# ── Agent Registration ────────────────────────────────────────────────────────


class RegisterAgentRequest(BaseModel):
    """JSON body for POST /v1/projects/{project_id}/agents."""

    kind: Literal["local", "cloud", "browser", "system"] = Field(
        ...,
        description="Agent runtime kind.",
    )
    name: str | None = Field(
        None,
        max_length=255,
        description="Optional human-readable name for display.",
    )


class RegisterAgentResponse(BaseModel):
    """Response returned after successful agent registration."""

    agent_id: str
    api_key: str
    kind: str
    name: str | None = None


from loom.db import get_session
from loom.models import Agent as AgentModel, Project


@router.post(
    "/projects/{project_id}/agents",
    response_model=RegisterAgentResponse,
    responses={
        201: {"description": "Agent registered successfully"},
        404: {"description": "Project not found"},
        422: {"description": "Validation error"},
    },
    status_code=201,
)
async def register_agent(
    project_id: uuid.UUID,
    body: RegisterAgentRequest,
    session=Depends(get_session),
) -> RegisterAgentResponse:
    """Register a new agent for a project.

    Creates an ``Agent`` record in the database and returns the agent's
    UUID as both ``agent_id`` and ``api_key`` (MVP auth — the bearer
    token equals the agent UUID).

    No authentication required (matching the extension setup endpoint
    pattern).  The project must exist.
    """
    # Verify project exists
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")

    # Create agent
    agent = AgentModel(
        project_id=project_id,
        kind=body.kind,
        name=body.name,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    agent_id = str(agent.id)
    return RegisterAgentResponse(
        agent_id=agent_id,
        api_key=agent_id,
        kind=agent.kind,
        name=agent.name,
    )
