"""Event type definitions for Phase 2.5 WebSocket broadcasting.

This module defines the event strings used for real-time presence
events.  Schema-only — no WebSocket implementation in this phase.
"""

from __future__ import annotations

from typing import Literal

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


# ── Event type literals (used as discriminator) ────────────────────────────

AgentEventType = Literal[
    "agent_online",
    "agent_heartbeat",
    "agent_offline",
    "agent_lock",
    "agent_unlock",
]

__all__ = [
    "AgentOnlineEventPayload",
    "AgentHeartbeatEventPayload",
    "AgentOfflineEventPayload",
    "AgentLockEventPayload",
    "AgentUnlockEventPayload",
    "AgentEventType",
]
