"""Conflict management REST router.

Provides endpoints to list and resolve ``pending_branches`` records
created when overlapping version conflicts are detected.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import AuthContext, require_auth
from loom.db import get_session
from loom.models import Agent, PendingBranch

router = APIRouter()


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> None:
    """Verify the agent belongs to the project. Raises 404 if not."""
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.project_id != project_id:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")


class ResolveConflictRequest(BaseModel):
    """JSON body for POST /v1/projects/{id}/conflicts/{branch_id}/resolve."""

    resolution: str


@router.get(
    "/{project_id}/conflicts",
    responses={
        200: {"description": "List of pending conflicts"},
        401: {"description": "Unauthorized"},
    },
)
async def list_conflicts(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """List all unresolved (pending) conflicts for a project."""
    await _verify_project_access(session, project_id, auth.agent_id)

    rows = (
        await session.execute(
            text(
                "SELECT pb.id, pb.context_unit_id, pb.conflict_type, "
                "       pb.resolution, pb.created_at, pb.branch_id "
                "FROM pending_branches pb "
                "JOIN context_units cu ON cu.id = pb.context_unit_id "
                "WHERE cu.project_id = :pid "
                "AND pb.resolution = 'pending' "
                "ORDER BY pb.created_at DESC"
            ),
            {"pid": project_id},
        )
    ).mappings().all()

    return [
        {
            "id": str(row["id"]),
            "context_unit_id": str(row["context_unit_id"]),
            "conflict_type": row["conflict_type"],
            "resolution": row["resolution"],
            "created_at": row["created_at"].isoformat(),
            "branch_id": str(row["branch_id"]) if row["branch_id"] else None,
        }
        for row in rows
    ]


@router.post(
    "/{project_id}/conflicts/{branch_id}/resolve",
    responses={
        200: {"description": "Conflict resolved"},
        404: {"description": "Conflict not found"},
        401: {"description": "Unauthorized"},
    },
)
async def resolve_conflict(
    project_id: uuid.UUID,
    branch_id: uuid.UUID,
    body: ResolveConflictRequest,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Resolve a pending conflict by updating its resolution status."""
    await _verify_project_access(session, project_id, auth.agent_id)

    branch = await session.get(PendingBranch, branch_id)
    if branch is None:
        raise HTTPException(status_code=404, detail="Conflict not found")

    # Validate resolution value
    valid_resolutions = {"pending", "auto_merged", "resolved"}
    if body.resolution not in valid_resolutions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution. Must be one of: {', '.join(sorted(valid_resolutions))}",
        )

    branch.resolution = body.resolution
    await session.commit()

    return {
        "id": str(branch.id),
        "resolution": branch.resolution,
    }
