"""Project management REST router.

Phase 1.11 — Browser Extension Core.
Provides:
- GET /v1/projects — list projects (for popup dropdown)
- POST /v1/projects — create a project (returns browser agent for extension)
- POST /v1/projects/{id}/link/chat — link a chat URL to a project
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import AuthContext, require_auth
from loom.db import get_session
from loom.services.links.service import link_chat
from loom.services.projects.service import create_project, list_projects

router = APIRouter()


# ── Request / Response Models ────────────────────────────────────────────────


class CreateProjectRequest(BaseModel):
    """JSON body for POST /v1/projects."""

    name: str = Field(..., description="Human-readable project name", min_length=1)


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


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[dict],
    responses={
        200: {"description": "List of all projects"},
        401: {"description": "Missing or invalid auth"},
    },
)
async def list_projects_endpoint(
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Return all projects as a simple list (for popup dropdown)."""
    return await list_projects(session)


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
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a project.  Auto-creates a ``browser``-kind agent whose
    UUID serves as the bearer token for the extension."""
    return await create_project(session, name=body.name)


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
) -> dict:
    """Link a chat URL to a project.  Idempotent: sending the same
    ``chat_url`` twice returns the same link."""
    try:
        return await link_chat(
            session,
            project_id=project_id,
            chat_url=body.chat_url,
            title=body.title,
            platform=body.platform,
        )
    except ValueError as exc:
        error_code = str(exc)
        status_map: dict[str, int] = {
            "PROJECT_NOT_FOUND": 404,
        }
        status = status_map.get(error_code, 400)
        raise HTTPException(status_code=status, detail=error_code)
