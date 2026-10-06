"""Context unit REST router.

Provides GET /{project_id}/context (list / read) and
POST /{project_id}/context (write new context unit).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.auth import AuthContext, require_auth
from loom.api.dependencies import get_redis
from loom.db import get_session
from loom.schemas.events import ProjectEvent
from loom.services.context.bundle import build_context_bundle
from loom.services.context.service import (
    VersionConflict,
    list_context_history,
    list_context_sources,
    read_context,
    write_context,
)
from loom.services.events.manager import connection_manager

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
    version: int | None = Field(
        None,
        description="Version in the parent lineage. Computed when omitted.",
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
    source_url: HttpUrl | None = Field(
        None,
        description="URL the content was pushed from (used by browser extension).",
        max_length=2048,
    )
    source_type: str | None = Field(
        None,
        description="Originating application. Defaults from the authenticated agent kind.",
    )
    source_session_id: str | None = Field(
        None,
        description="Originating agent or chat session identifier.",
        max_length=255,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured task-result metadata.",
    )


class ContextUnitResponse(BaseModel):
    """JSON response for a written context unit."""

    id: str
    client_uuid: str
    created_at: str
    occurred_at: str | None = None
    version: int
    source_type: str
    source_session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReadContextQuery(BaseModel):
    """Query parameters for GET /v1/projects/{id}/context."""

    query: str | None = Field(
        None,
        max_length=500,
        description="Natural-language keyword query. Empty returns recent units.",
    )
    budget: int = Field(
        4096,
        description="Max tokens to return (default 4096, max 32000).",
        ge=1,
        le=32000,
    )
    scope: Literal["onboarding", "task", "full"] = Field(
        "task",
        description="One of: onboarding, task (default), full.",
    )


class ReadContextUnitModel(BaseModel):
    """Individual context unit returned in a read response."""

    id: str
    type: str
    trust_tier: str
    content: str
    source_url: str | None = None
    source_type: str = "mcp_agent"
    source_session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    occurred_at: str | None = None
    agent_id: str
    agent_name: str | None = None
    version: int = 1
    parent_ids: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0


class ReadContextResponse(BaseModel):
    """Response from GET /v1/projects/{id}/context."""

    units: list[ReadContextUnitModel]
    total_tokens: int
    budget_used: int
    truncated: bool


class BundleQuery(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=10000)
    budget: int = Field(4096, ge=1, le=32000)


class BundleResponse(BaseModel):
    brief: str
    evidence: list[dict[str, Any]]
    total_tokens: int
    truncated: bool


class ContextHistoryQuery(BaseModel):
    """Cursor pagination parameters for the human-facing history view."""

    limit: int = Field(100, ge=1, le=200)
    cursor: str | None = Field(None, max_length=512)
    source_type: str | None = Field(None, max_length=64)
    source_session_id: str | None = Field(None, max_length=255)
    unit_type: Literal[
        "message", "decision", "artifact_ref", "task_result", "summary"
    ] | None = Field(None, alias="type")


class ContextHistoryResponse(BaseModel):
    """A stable chronological page that does not apply token truncation."""

    units: list[ReadContextUnitModel]
    next_cursor: str | None
    has_more: bool


class ContextSourceModel(BaseModel):
    """One observed provenance source within a project."""

    source_type: str
    source_session_id: str | None = None
    source_url: str | None = None
    agent_id: str
    agent_name: str | None = None
    unit_count: int
    first_seen_at: str
    last_seen_at: str
    first_occurred_at: str | None = None
    last_occurred_at: str | None = None


class ContextSourcesResponse(BaseModel):
    sources: list[ContextSourceModel]


class ConversationMessageRequest(BaseModel):
    client_uuid: uuid.UUID
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=100000)
    occurred_at: datetime
    turn_id: str | None = Field(None, max_length=255)
    message_id: str | None = Field(None, max_length=255)
    sequence: int = Field(ge=0)
    session_title: str | None = Field(None, max_length=500)
    parent_client_uuid: uuid.UUID | None = None


class ConversationBatchRequest(BaseModel):
    source_type: Literal["codex_cli", "claude_code", "opencode"]
    source_session_id: str = Field(min_length=1, max_length=255)
    capture_method: Literal["live", "import"] = "live"
    messages: list[ConversationMessageRequest] = Field(min_length=1, max_length=100)


@router.post("/{project_id}/conversations/messages")
async def ingest_conversation_messages(
    project_id: uuid.UUID,
    body: ConversationBatchRequest,
    request: Request,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, list[dict[str, str | bool]]]:
    """Accept bounded terminal turns from an authenticated project agent."""
    if len(await request.body()) > 1_000_000:
        raise HTTPException(413, "CONVERSATION_BATCH_TOO_LARGE")
    if auth.project_id != project_id:
        raise HTTPException(403, "AGENT_MISMATCH")
    from sqlalchemy import select

    from loom.models import Agent, ContextUnit

    agent = await session.get(Agent, auth.agent_id)
    if agent is None or agent.kind != "local":
        raise HTTPException(403, "LOCAL_AGENT_REQUIRED")
    foreign_session = (
        await session.execute(
            select(ContextUnit.id)
            .where(
                ContextUnit.source_type == body.source_type,
                ContextUnit.source_session_id == body.source_session_id,
                ContextUnit.project_id != project_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if foreign_session is not None:
        raise HTTPException(403, "CROSS_PROJECT_SESSION")
    results: list[dict[str, str | bool]] = []
    new_units: list[tuple[str, str]] = []
    known: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    for message in body.messages:
        if message.occurred_at.tzinfo is None or not message.content.strip():
            raise HTTPException(400, "INVALID_CONVERSATION_MESSAGE")
        known_parent = known.get(message.parent_client_uuid) if message.parent_client_uuid else None
        parent_id = known_parent[0] if known_parent else None
        if known_parent and known_parent[1] != "user":
            raise HTTPException(400, "INVALID_CONVERSATION_PARENT")
        if message.parent_client_uuid and parent_id is None:
            parent = (
                await session.execute(
                    select(ContextUnit).where(
                        ContextUnit.client_uuid == message.parent_client_uuid,
                        ContextUnit.project_id == project_id,
                        ContextUnit.source_type == body.source_type,
                        ContextUnit.source_session_id == body.source_session_id,
                    )
                )
            ).scalar_one_or_none()
            if parent is None or parent.context_metadata.get("conversation_role") != "user":
                raise HTTPException(400, "INVALID_CONVERSATION_PARENT")
            parent_id = parent.id
        if message.role == "user" and parent_id is not None:
            raise HTTPException(400, "INVALID_CONVERSATION_PARENT")
        metadata = {
            "conversation_role": message.role,
            "turn_id": message.turn_id,
            "message_id": message.message_id,
            "message_sequence": message.sequence,
            "session_title": message.session_title,
            "capture_method": body.capture_method,
        }
        try:
            unit, is_new = await write_context(
                session,
                project_id,
                auth.agent_id,
                client_uuid=message.client_uuid,
                type_="message",
                content=message.content,
                version=None,
                source_type=body.source_type,
                source_session_id=body.source_session_id,
                metadata=metadata,
                parent_ids=[parent_id] if parent_id else None,
                occurred_at=message.occurred_at,
                conversation_role=message.role,
                commit=False,
            )
        except ValueError as exc:
            await session.rollback()
            code = str(exc)
            raise HTTPException(409 if code == "IDEMPOTENCY_KEY_REUSED" else 400, code) from exc
        if is_new:
            new_units.append((str(unit.id), unit.content))
        known[message.client_uuid] = (unit.id, message.role)
        results.append(
            {"id": str(unit.id), "client_uuid": str(unit.client_uuid), "created": is_new}
        )
    await session.commit()
    if new_units:
        from loom.services.retrieval.queue import enqueue_embedding_job

        for unit_id, content in new_units:
            try:
                await enqueue_embedding_job(unit_id, content)
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "Failed to enqueue embedding job for conversation unit %s", unit_id
                )
    return {"messages": results}


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get(
    "/{project_id}/context/history",
    response_model=ContextHistoryResponse,
    responses={
        200: {"description": "Chronological context history page"},
        400: {"description": "Malformed pagination cursor"},
        401: {"description": "Missing or invalid auth"},
        403: {"description": "Agent does not belong to this project"},
        404: {"description": "Project not found"},
    },
)
async def context_history_endpoint(
    project_id: uuid.UUID,
    params: ContextHistoryQuery = Depends(),
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List complete context for dashboards without retrieval-budget limits."""
    try:
        return await list_context_history(
            session,
            project_id,
            auth.agent_id,
            limit=params.limit,
            cursor=params.cursor,
            source_type=params.source_type,
            source_session_id=params.source_session_id,
            unit_type=params.unit_type,
        )
    except ValueError as exc:
        error_code = str(exc)
        status_map = {
            "INVALID_CURSOR": 400,
            "PROJECT_NOT_FOUND": 404,
            "AGENT_MISMATCH": 403,
        }
        raise HTTPException(
            status_code=status_map.get(error_code, 400),
            detail=error_code,
        )


@router.get(
    "/{project_id}/context/sources",
    response_model=ContextSourcesResponse,
    responses={
        200: {"description": "Observed context provenance sources"},
        401: {"description": "Missing or invalid auth"},
        403: {"description": "Agent does not belong to this project"},
        404: {"description": "Project not found"},
    },
)
async def context_sources_endpoint(
    project_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List browser and harness sources observed in project context."""
    try:
        return await list_context_sources(
            session,
            project_id,
            auth.agent_id,
        )
    except ValueError as exc:
        error_code = str(exc)
        status_map = {
            "PROJECT_NOT_FOUND": 404,
            "AGENT_MISMATCH": 403,
        }
        raise HTTPException(
            status_code=status_map.get(error_code, 400),
            detail=error_code,
        )


@router.post("/{project_id}/context/bundle", response_model=BundleResponse)
async def context_bundle_endpoint(
    project_id: uuid.UUID,
    params: BundleQuery,
    auth: AuthContext = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Retrieve a cited context bundle for one submitted prompt."""
    try:
        return await build_context_bundle(
            session, project_id, auth.agent_id, prompt=params.prompt, budget=params.budget
        )
    except ValueError as exc:
        raise HTTPException(
            status_code={"PROJECT_NOT_FOUND": 404, "AGENT_MISMATCH": 403}.get(str(exc), 400),
            detail=str(exc),
        ) from exc


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
) -> dict[str, Any]:
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
    redis: redis_async.Redis | None = Depends(get_redis),
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
            source_url=str(body.source_url) if body.source_url else None,
            source_type=body.source_type,
            source_session_id=body.source_session_id,
            metadata=body.metadata,
            redis=redis,
        )
    except VersionConflict as vc:
        # The service flushed a PendingBranch before raising, but the
        # transaction hasn't committed yet.  Commit now so the branch
        # is persisted (no other mutations are pending at this point).
        await session.commit()

        # ── Fire-and-forget broadcast ────────────────────────────────────
        conflict_event = ProjectEvent(
            type="conflict_created",
            project_id=str(project_id),
            payload={
                "pending_branch_id": str(vc.pending_branch_id),
                "context_unit_id": str(vc.context_unit_id),
                "conflict_type": "version_conflict",
            },
            timestamp=datetime.now(UTC).isoformat(),
        ).model_dump()
        asyncio.create_task(connection_manager.broadcast(str(project_id), conflict_event))

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
            "PARENT_PROJECT_MISMATCH": 403,
            "BRANCH_PROJECT_MISMATCH": 403,
            "BRANCH_NOT_OPEN": 409,
            "IDEMPOTENCY_KEY_REUSED": 409,
            "INVALID_SOURCE_TYPE": 400,
            "SOURCE_TYPE_DENIED": 403,
            "INVALID_SOURCE_SESSION_ID": 400,
        }
        status = status_map.get(error_code, 400)
        raise HTTPException(status_code=status, detail=error_code)

    status_code = 201 if is_new else 200

    # ── Fire-and-forget broadcast ────────────────────────────────────────
    if is_new:
        event = ProjectEvent(
            type="context_created",
            project_id=str(project_id),
            payload={
                "context_unit_id": str(unit.id),
                "type": body.type,
                "content_preview": body.content[:200],
                "agent_id": str(auth.agent_id),
                "version": unit.version,
                "source_type": unit.source_type,
                "source_session_id": unit.source_session_id,
            },
            timestamp=datetime.now(UTC).isoformat(),
        ).model_dump()
        asyncio.create_task(connection_manager.broadcast(str(project_id), event))

    return JSONResponse(
        content={
            "id": str(unit.id),
            "client_uuid": str(unit.client_uuid),
            "created_at": unit.created_at.isoformat() if unit.created_at else "",
            "occurred_at": unit.occurred_at.isoformat() if unit.occurred_at else None,
            "version": unit.version,
            "source_type": unit.source_type,
            "source_session_id": unit.source_session_id,
            "metadata": unit.context_metadata,
        },
        status_code=status_code,
    )
