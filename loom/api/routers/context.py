"""Context unit REST router.

Provides GET /{project_id}/context (list / read) and
POST /{project_id}/context (write new context unit).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import AuthContext, require_auth
from loom.db import get_session
from loom.services.context.service import write_context

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
    parent_ids: list[str] | None = Field(
        None,
        description="UUIDs of parent context units this derives from.",
    )
    parent_relations: list[str] | None = Field(
        None,
        description="Edge relation for each parent (defaults to derived_from).",
    )


class ContextUnitResponse(BaseModel):
    """JSON response for a written context unit."""

    id: str
    client_uuid: str
    created_at: str
    version: int


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/{project_id}/context")
async def read_context(
    project_id: str,
) -> dict[str, Any]:
    """List / read context units (stub — Phase 1.3)."""
    return {"project_id": project_id, "units": [], "total_tokens": 0}


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
        )
    except ValueError as exc:
        error_code = str(exc)
        status_map: dict[str, int] = {
            "PROJECT_NOT_FOUND": 404,
            "AGENT_MISMATCH": 403,
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
