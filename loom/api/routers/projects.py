"""Project management REST router.

Phase 1.11 — Browser Extension Core.
Provides:
- GET /v1/projects — list projects (for popup dropdown)
- POST /v1/projects — create a project (returns browser agent for extension)
- POST /v1/projects/{id}/link/chat — link a chat URL to a project
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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
from loom.models import Agent, Project
from loom.services.accounts.rate_limit import (
    RateLimitExceededError,
    RateLimitUnavailableError,
    enforce_rate_limit,
)
from loom.services.accounts.service import (
    create_user_project,
    get_membership,
    list_user_projects,
)
from loom.services.context.service import list_context_history
from loom.services.extension.service import EXTENSION_CHAT_LINK_NAME
from loom.services.links.service import link_chat
from loom.services.projects.service import create_project, get_project, list_projects

router = APIRouter()


# ── Request / Response Models ────────────────────────────────────────────────


class CreateProjectRequest(BaseModel):
    """JSON body for POST /v1/projects."""

    name: str = Field(..., description="Human-readable project name", min_length=1)
    client_kind: Literal["web", "cli", "extension"] = "web"
    client_name: str = Field("Loom Web", min_length=1, max_length=255)


class CreateProjectResponse(BaseModel):
    """Response from POST /v1/projects."""

    id: str
    name: str
    created_at: str
    agent_id: str
    api_key: str


class LinkChatRequest(BaseModel):
    """JSON body for POST /v1/projects/{id}/link/chat."""

    chat_url: str = Field(..., description="Full URL of the chat session")
    title: str = Field("", description="Human-readable chat title")
    platform: str = Field("", description="Chat platform name, e.g. claude.ai")


class LinkChatResponse(BaseModel):
    """Response from POST /v1/projects/{id}/link/chat."""

    id: str
    project_id: str
    chat_url: str
    title: str
    platform: str
    linked_at: str
    api_key: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> None:
    """Verify the agent belongs to the project. Raises 404 if not."""
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.project_id != project_id:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[dict[str, Any]],
    responses={
        200: {"description": "List of all projects"},
        401: {"description": "Missing or invalid auth"},
    },
)
async def list_projects_endpoint(
    auth: PrincipalContext = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Return membership projects for users or one project for agent keys."""
    if auth.kind == "user":
        assert auth.user_id is not None
        return await list_user_projects(session, auth.user_id)
    return await list_projects(session, auth.project_id)


@router.post(
    "",
    response_model=CreateProjectResponse,
    status_code=201,
    responses={
        201: {"description": "Project created with browser agent"},
        401: {"description": "Missing or invalid auth"},
        422: {"description": "Validation error"},
    },
)
async def create_project_endpoint(
    body: CreateProjectRequest,
    auth: PrincipalContext = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> dict[str, Any]:
    """Create a project and return one-time opaque browser credentials."""
    if auth.kind == "user":
        assert auth.user_id is not None
        try:
            await enforce_rate_limit(
                redis,
                operation="project-create",
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
        return await create_user_project(
            session,
            user_id=auth.user_id,
            name=body.name,
            client_kind=body.client_kind,
            client_name=body.client_name,
        )
    assert auth.agent_id is not None
    caller = await session.get(Agent, auth.agent_id)
    caller_project = await session.get(Project, auth.project_id)
    if (
        caller is None
        or caller.kind != "system"
        or caller_project is None
        or caller_project.name != EXTENSION_CHAT_LINK_NAME
    ):
        raise HTTPException(status_code=403, detail="BOOTSTRAP_CREDENTIAL_REQUIRED")
    result = await create_project(
        session,
        name=body.name,
        agent_kind="local" if body.client_kind == "cli" else "browser",
        agent_name=body.client_name,
    )
    caller.revoked_at = datetime.now(UTC)
    await session.commit()
    return result


@router.post(
    "/{project_id}/link/chat",
    response_model=LinkChatResponse,
    responses={
        200: {"description": "Chat linked (or was already linked)"},
        401: {"description": "Missing or invalid auth"},
        404: {"description": "Project not found"},
    },
)
async def link_chat_endpoint(
    project_id: uuid.UUID,
    body: LinkChatRequest,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Link a chat URL to a project.  Idempotent: sending the same
    ``chat_url`` twice returns the same link."""
    await _verify_project_access(session, project_id, auth.agent_id)
    try:
        return await link_chat(
            session,
            project_id=str(project_id),
            chat_url=body.chat_url,
            title=body.title,
            platform=body.platform,
        )
    except ValueError as exc:
        error_code = str(exc)
        status_map: dict[str, int] = {
            "PROJECT_NOT_FOUND": 404,
            "CHAT_ALREADY_LINKED": 409,
        }
        status = status_map.get(error_code, 400)
        raise HTTPException(status_code=status, detail=error_code)


@router.get(
    "/{project_id}",
    responses={
        200: {"description": "Project details"},
        401: {"description": "Unauthorized"},
        404: {"description": "Project not found"},
    },
)
async def get_project_endpoint(
    project_id: uuid.UUID,
    auth: PrincipalContext = Depends(require_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single project by ID."""
    if auth.kind == "user":
        assert auth.user_id is not None
        if await get_membership(session, auth.user_id, project_id) is None:
            raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    else:
        assert auth.agent_id is not None
        await _verify_project_access(session, project_id, auth.agent_id)
    try:
        return await get_project(session, project_id)
    except ValueError as exc:
        error_code = str(exc)
        if error_code == "PROJECT_NOT_FOUND":
            raise HTTPException(status_code=404, detail=error_code)
        raise HTTPException(status_code=400, detail=error_code)


@router.get("/{project_id}/history")
async def get_account_project_history(
    project_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=200),
    cursor: str | None = Query(None, max_length=512),
    auth: UserAuthContext = Depends(require_user_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Read complete project history through a human account membership."""

    if await get_membership(session, auth.user_id, project_id) is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    try:
        return await list_context_history(
            session,
            project_id,
            None,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=400 if code == "INVALID_CURSOR" else 404,
            detail=code,
        ) from exc
