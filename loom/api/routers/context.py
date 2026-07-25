"""Context unit REST router.

Provides GET /{project_id}/context (list / read) and
POST /{project_id}/context (write new context unit).
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import AuthContext, require_auth
from loom.db import get_session
from loom.services.context.service import (
    VersionConflict,
    read_context,
    write_context,
)

router = APIRouter()


# ── Request / Response Models ────────────────────────────────────────────────


class WriteContextRequest(BaseModel):
    """JSON body for POST /v1/projects/{id}/context."""

    client_uuid: uuid.UUID = Field(
        ...,
        description="Client-supplied idempotency key (unique across the project).",
    )
    type: str = Field(
        ...,
        description="One of: message, decision, artifact_ref, task_result, summary.",
    )
    content: str = Field(
        ...,
        description="Non-empty text content of the context unit.",
        min_length=1,
        max_length=100000,
    )
    version: int = Field(
        ...,
        description="Version in the parent lineage (parent.version + 1).",
        ge=1,
    )
    trust_tier: str | None = Field(
        None,
        description="One of: user, agent, external_tool. Defaults to agent.",
    )
    parent_ids: list[uuid.UUID] | None = Field(
        None,
        description="UUIDs of parent context units this derives from.",
    )
    parent_relations: list[str] | None = Field(
        None,
        description="Edge relation for each parent (defaults to derived_from).",
    )
    branch_id: uuid.UUID | None = Field(
        None,
        description="Branch ID to associate this write with (for Phase 2.1 coordination).",
    )


class ContextUnitResponse(BaseModel):
    """JSON response for a written context unit."""

    id: str
    client_uuid: str
    created_at: str
    version: int


class ReadContextQuery(BaseModel):
    """Query parameters for GET /v1/projects/{id}/context."""

    query: str | None = Field(
        None,
        description="Natural-language keyword query. Empty returns recent units.",
    )
    budget: int = Field(
        4096,
        description="Max tokens to return (default 4096, max 32000).",
        ge=1,
        le=32000,
    )
    scope: str = Field(
        "task",
        description="One of: onboarding, task (default), full.",
    )


class ReadContextUnitModel(BaseModel):
    """A single context unit in the read response."""

    id: str
    type: str
    trust_tier: str
    content: str
    created_at: str
    agent_id: str
    parent_ids: list[str] = []
    relevance_score: float = 0.0


class ReadContextResponse(BaseModel):
    """Response from GET /v1/projects/{id}/context."""

    units: list[ReadContextUnitModel]
    total_tokens: int
    budget_used: int
    truncated: bool


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "/{project_id}/context",
    response_model=ReadContextResponse,
    responses={
        200: {"description": "Context units retrieved"},
        401: {"description": "Missing or invalid auth"},
        403: {"description": "Agent does not belong to this project"},
        404: {"description": "Project not found"},
    },
)
async def read_context_endpoint(
    project_id: uuid.UUID,
    params: ReadContextQuery = Depends(),
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Retrieve context units for a project.

    Supports keyword full-text search, token-budget-aware packing, and
    scope filtering (onboarding / task / full).
    """
    try:
        result = await read_context(
            session,
            project_id,
            auth.agent_id,
            query=params.query,
            budget=params.budget,
            scope=params.scope,
        )
    except ValueError as exc:
        error_code = str(exc)
        status_map: dict[str, int] = {
            "PROJECT_NOT_FOUND": 404,
            "AGENT_MISMATCH": 403,
        }
        status = status_map.get(error_code, 400)
        raise HTTPException(status_code=status, detail=error_code)

    return result


@router.post(
    "/{project_id}/context",
    response_model=ContextUnitResponse,
    responses={
        200: {"description": "Idempotent replay — unit already existed"},
        201: {"description": "Unit created"},
        400: {"description": "Validation error (invalid type, empty content, etc.)"},
        403: {"description": "Agent does not belong to this project"},
        404: {"description": "Project or parent not found"},
        409: {"description": "Version conflict"},
    },
)
async def write_context_endpoint(
    project_id: uuid.UUID,
    body: WriteContextRequest,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Write a new context unit.

    Idempotent: sending the same ``client_uuid`` twice returns the existing
    record (200 instead of 201).  Version-conflict detection ensures safe
    concurrent writes: the incoming version must equal max(parent.version) + 1.
    """
    try:
        unit, is_new = await write_context(
            session,
            project_id,
            auth.agent_id,
            client_uuid=body.client_uuid,
            type_=body.type,
            content=body.content,
            version=body.version,
            trust_tier=body.trust_tier,
            parent_ids=body.parent_ids,
            parent_relations=body.parent_relations,
            branch_id=body.branch_id,
        )
    except VersionConflict as vc:
        # The service flushed a PendingBranch before raising, but the
        # transaction hasn't committed yet.  Commit now so the branch
        # is persisted (no other mutations are pending at this point).
        await session.commit()
        return JSONResponse(
            content={
                "detail": "VERSION_CONFLICT",
                "current_version": vc.current_version,
                "claimed_version": vc.claimed_version,
                "pending_branch_id": str(vc.pending_branch_id),
                "context_unit_id": str(vc.context_unit_id),
            },
            status_code=409,
        )
    except ValueError as exc:
        error_code = str(exc)
        status_map: dict[str, int] = {
            "PROJECT_NOT_FOUND": 404,
            "AGENT_MISMATCH": 403,
            "TRUST_TIER_DENIED": 403,
            "INVALID_TYPE": 400,
            "EMPTY_CONTENT": 400,
            "CONFLICT": 409,
            "PARENT_NOT_FOUND": 404,
        }
        status = status_map.get(error_code, 400)
        raise HTTPException(status_code=status, detail=error_code)

    status_code = 201 if is_new else 200

    return JSONResponse(
        content={
            "id": str(unit.id),
            "client_uuid": str(unit.client_uuid),
            "created_at": unit.created_at.isoformat() if unit.created_at else "",
            "version": unit.version,
        },
        status_code=status_code,
    )
