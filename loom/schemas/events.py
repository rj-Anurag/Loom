"""Event type definitions for Phase 2.5 WebSocket broadcasting.

This module defines the event strings and payload types used for real-time
presence events and project-level events.  Schema and envelope only — the
WebSocket implementation lives in ``loom.api.routers.events`` and
``loom.services.events.manager``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

# ── Agent presence events ──────────────────────────────────────────────────

AgentOnlineEventPayload = dict[str, Any]
"""``{ "agent_id": str, "kind": str, "status": str }``"""

AgentHeartbeatEventPayload = dict[str, Any]
"""``{ "agent_id": str, "status": str, "task_id": str }``"""

AgentOfflineEventPayload = dict[str, Any]
"""``{ "agent_id": str }``"""

AgentLockEventPayload = dict[str, Any]
"""``{ "agent_id": str, "context_unit_id": str }``"""

AgentUnlockEventPayload = dict[str, Any]
"""``{ "agent_id": str, "context_unit_id": str }``"""

# ── Project-level events ───────────────────────────────────────────────────

ContextCreatedEventPayload = dict[str, Any]
"""Context-created payload fields: unit ID, type, preview, agent ID, version."""

ConflictCreatedEventPayload = dict[str, Any]
"""``{ "pending_branch_id": str, "context_unit_id": str, "conflict_type": str }``"""


# ── Event type literals ────────────────────────────────────────────────────

AgentEventType = Literal[
    "agent_online",
    "agent_heartbeat",
    "agent_offline",
    "agent_lock",
    "agent_unlock",
]

ProjectEventType = Literal[
    "agent_online",
    "agent_heartbeat",
    "agent_offline",
    "agent_lock",
    "agent_unlock",
    "context_created",
    "conflict_created",
]

# ── Event envelope ─────────────────────────────────────────────────────────


class ProjectEvent(BaseModel):
    """Consistent event envelope for all WebSocket broadcasts.

    Every WS message follows this structure so clients can discriminate
    event types without string-parsing the payload shape.
    """

    type: str  # One of ProjectEventType values
    project_id: str
    payload: dict[str, Any]
    timestamp: str  # ISO 8601 (set at construction time)


def make_event(
    event_type: str,
    project_id: str,
    payload: dict[str, Any],
) -> ProjectEvent:
    """Convenience factory — sets timestamp to now."""
    return ProjectEvent(
        type=event_type,
        project_id=project_id,
        payload=payload,
        timestamp=datetime.now(UTC).isoformat(),
    )


__all__ = [
    "AgentOnlineEventPayload",
    "AgentHeartbeatEventPayload",
    "AgentOfflineEventPayload",
    "AgentLockEventPayload",
    "AgentUnlockEventPayload",
    "ContextCreatedEventPayload",
    "ConflictCreatedEventPayload",
    "AgentEventType",
    "ProjectEventType",
    "ProjectEvent",
    "make_event",
]
