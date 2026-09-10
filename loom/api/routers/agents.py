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
from datetime import UTC, datetime
from typing import Any, Literal

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import (
    AuthContext,
    PrincipalContext,
    UserAuthContext,
    require_auth,
    require_principal,
    require_user_auth,
)
from loom.api.dependencies import get_redis
from loom.config import settings
from loom.db import get_session
from loom.models import Agent as AgentModel
from loom.models import Project
from loom.schemas.events import ProjectEvent
from loom.security import generate_api_key, hash_api_key
from loom.services.accounts.rate_limit import (
    RateLimitExceededError,
    RateLimitUnavailableError,
    enforce_rate_limit,
)
from loom.services.accounts.service import get_membership, provision_agent
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
            timestamp=datetime.now(UTC).isoformat(),
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

    kind: Literal["local", "cloud", "browser"] = Field(
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
    auth: PrincipalContext = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> RegisterAgentResponse:
    """Register a new agent for a project.

    Creates an ``Agent`` record and returns the opaque bearer key once.
    Only its SHA-256 digest is persisted in ``credentials_ref``.

    The caller must already hold a credential for this project. This prevents
    an attacker who learns a UUID from minting a new bearer credential.
    """
    if auth.kind == "user":
        assert auth.user_id is not None
        try:
            await enforce_rate_limit(
                redis,
                operation="credential-issue",
                identifier=str(auth.user_id),
            )
        except RateLimitExceededError as exc:
            raise HTTPException(
                status_code=429,
                detail="TOO_MANY_ATTEMPTS",
                headers={"Retry-After": str(settings.auth_rate_limit_window_seconds)},
            ) from exc
        except RateLimitUnavailableError as exc:
            raise HTTPException(status_code=503, detail="AUTH_SERVICE_UNAVAILABLE") from exc
        try:
            agent, api_key = await provision_agent(
                session,
                user_id=auth.user_id,
                project_id=project_id,
                kind=body.kind,
                name=body.name or "Loom Client",
            )
        except ValueError as exc:
            error_code = str(exc)
            status = 403 if error_code == "INSUFFICIENT_ROLE" else 404
            raise HTTPException(status_code=status, detail=error_code) from exc
        return RegisterAgentResponse(
            agent_id=str(agent.id),
            api_key=api_key,
            kind=agent.kind,
            name=agent.name,
        )

    if auth.project_id != project_id:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    if settings.environment != "development" and not settings.allow_agent_key_enrollment:
        raise HTTPException(status_code=403, detail="ACCOUNT_SESSION_REQUIRED")

    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")

    # Create agent
    agent = AgentModel(
        project_id=project_id,
        kind=body.kind,
        name=body.name,
    )
    api_key = generate_api_key()
    agent.credentials_ref = hash_api_key(api_key)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)

    return RegisterAgentResponse(
        agent_id=str(agent.id),
        api_key=api_key,
        kind=agent.kind,
        name=agent.name,
    )


@router.get("/projects/{project_id}/agents")
async def list_project_agents(
    project_id: uuid.UUID,
    auth: UserAuthContext = Depends(require_user_auth),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """List credential metadata for an account member; never return raw keys."""

    if await get_membership(session, auth.user_id, project_id) is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    result = await session.execute(
        select(AgentModel)
        .where(AgentModel.project_id == project_id)
        .order_by(AgentModel.created_at.desc())
    )
    return [
        {
            "id": str(agent.id),
            "kind": agent.kind,
            "name": agent.name,
            "key_hint": agent.key_hint,
            "created_at": agent.created_at.isoformat() if agent.created_at else "",
            "last_used_at": agent.last_used_at.isoformat() if agent.last_used_at else None,
            "expires_at": agent.expires_at.isoformat() if agent.expires_at else None,
            "revoked_at": agent.revoked_at.isoformat() if agent.revoked_at else None,
        }
        for agent in result.scalars().all()
    ]


@router.delete("/projects/{project_id}/agents/{agent_id}", status_code=204)
async def revoke_project_agent(
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
    auth: UserAuthContext = Depends(require_user_auth),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke a project key without deleting its provenance record."""

    membership = await get_membership(session, auth.user_id, project_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="INSUFFICIENT_ROLE")
    agent = await session.get(AgentModel, agent_id)
    if agent is None or agent.project_id != project_id:
        raise HTTPException(status_code=404, detail="AGENT_NOT_FOUND")
    if agent.kind == "system":
        raise HTTPException(status_code=403, detail="SYSTEM_AGENT_CANNOT_BE_REVOKED")
    if agent.revoked_at is None:
        agent.revoked_at = datetime.now(UTC)
        await session.commit()
