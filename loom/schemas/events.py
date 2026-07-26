"""Event type definitions for Phase 2.5 WebSocket broadcasting.

This module defines the event strings and payload types used for real-time
presence events and project-level events.  Schema and envelope only — the
WebSocket implementation lives in ``loom.api.routers.events`` and
``loom.services.events.manager``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

# ── Agent presence events ──────────────────────────────────────────────────

AgentOnlineEventPayload = dict
"""``{ "agent_id": str, "kind": str, "status": str }``"""

AgentHeartbeatEventPayload = dict
"""``{ "agent_id": str, "status": str, "task_id": str }``"""

AgentOfflineEventPayload = dict
"""``{ "agent_id": str }``"""

AgentLockEventPayload = dict
"""``{ "agent_id": str, "context_unit_id": str }``"""

AgentUnlockEventPayload = dict
"""``{ "agent_id": str, "context_unit_id": str }``"""

# ── Project-level events ───────────────────────────────────────────────────

ContextCreatedEventPayload = dict
"""``{ "context_unit_id": str, "type": str, "content_preview": str, "agent_id": str, "version": int }``"""

ConflictCreatedEventPayload = dict
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
    payload: dict
    timestamp: str  # ISO 8601 (set at construction time)

    def model_dump(self, *args, **kwargs):
        """Merge payload into the top-level envelope for WS transmission."""
        return {
            "type": self.type,
            "project_id": self.project_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


def make_event(
    event_type: str,
    project_id: str,
    payload: dict,
) -> ProjectEvent:
    """Convenience factory — sets timestamp to now."""
    return ProjectEvent(
        type=event_type,
        project_id=project_id,
        payload=payload,
        timestamp=datetime.now(timezone.utc).isoformat(),
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
