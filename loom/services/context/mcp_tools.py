"""MCP Tool definitions for the Loom Context Server.

Each tool wraps a service-layer function (``read_context``, ``write_context``)
and presents it as an MCP-compatible tool definition.  Tools call the Python
service layer directly (no HTTP) for minimal latency when the agent is
co-located with the daemon.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from loom.services.context.service import read_context, write_context


_CLIENT_UUID_NAMESPACE = uuid.NAMESPACE_DNS
"""Namespace used for deterministic client_uuid generation (UUID v5)."""

TIER_ORDER: dict[str, int] = {
    "user": 3,
    "agent": 2,
    "external_tool": 1,
}
"""Numeric ordering for trust-tier filtering. Higher = more trusted."""


# ── Base class ────────────────────────────────────────────────────────────────


class MCPTool:
    """Base class for a single MCP tool.

    Subclasses must set ``name``, ``description``, ``input_schema`` and
    implement ``call()``.
    """

    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {}

    def __init__(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> None:
        self.session = session
        self.project_id = project_id
        self.agent_id = agent_id

    def definition(self) -> dict[str, Any]:
        """Return an MCP tool definition dict."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool and return a result dict."""
        raise NotImplementedError


# ── Concrete tools ────────────────────────────────────────────────────────────


class ReadContextTool(MCPTool):
    """Retrieve context units relevant to the current task."""

    name = "read_context"
    description = (
        "Retrieve relevant context from the shared project store. "
        "Returns a token-budgeted, relevance-ranked bundle of context units "
        "that are semantically related to the task description."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Description of what the agent is working on — used for full-text relevance ranking",
            },
            "token_budget": {
                "type": "integer",
                "description": "Maximum tokens to return (default 4096, max 32000)",
                "default": 4096,
            },
            "scope": {
                "type": "string",
                "enum": ["task", "onboarding", "full"],
                "description": "Scope of context to retrieve — 'task' (all types), 'onboarding' (summaries only), 'full' (everything)",
                "default": "task",
            },
            "min_trust_tier": {
                "type": "string",
                "enum": ["user", "agent", "external_tool"],
                "description": "Minimum trust tier to include — filters out results below this tier",
                "default": "external_tool",
            },
        },
        "required": ["task_description"],
    }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        task_description = args.get("task_description", "").strip()
        if not task_description:
            return {"error": "Missing required field: task_description"}

        token_budget = args.get("token_budget", 4096)
        scope = args.get("scope", "task")
        min_trust_tier = args.get("min_trust_tier", "external_tool")

        try:
            result = await read_context(
                self.session,
                self.project_id,
                self.agent_id,
                query=task_description,
                budget=token_budget,
                scope=scope,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        # ── Post-filter by minimum trust tier ────────────────────────────
        min_tier_value = TIER_ORDER.get(min_trust_tier, 1)

        result["units"] = [
            u
            for u in result["units"]
            if TIER_ORDER.get(u["trust_tier"], 0) >= min_tier_value
        ]

        # Recompute totals after filtering
        total = sum(
            max(1, len(u["content"]) // 4) for u in result["units"]
        )
        result["total_tokens"] = total
        result["budget_used"] = total

        return result


class WriteContextTool(MCPTool):
    """Write a new context unit to the shared project store."""

    name = "write_context"
    description = (
        "Write a new context unit to the shared project store. "
        "Results, decisions, messages, and artifact references are all "
        "written through this single tool. "
        "The tool is idempotent — writing the same content+type twice "
        "returns the same unit ID."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The text content to store",
            },
            "type": {
                "type": "string",
                "enum": ["message", "decision", "artifact_ref", "task_result", "summary"],
                "description": "Type of context unit — affects search ranking and scope filters",
            },
            "parent_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "UUIDs of parent context units this unit derives from or references",
            },
            "parent_relations": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["derived_from", "supersedes", "references", "merged_from"],
                },
                "description": "Relation labels for each parent (parallel array to parent_ids)",
            },
        },
        "required": ["content", "type"],
    }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        content = args.get("content", "").strip()
        type_ = args.get("type", "").strip()

        if not content:
            return {"error": "Missing required field: content"}
        if not type_:
            return {"error": "Missing required field: type"}

        # Deterministic client_uuid for built-in idempotency
        client_uuid = uuid.uuid5(_CLIENT_UUID_NAMESPACE, f"{type_}:{content}")

        parent_ids: list[str] | None = args.get("parent_ids")
        parent_relations: list[str] | None = args.get("parent_relations")

        # ── Auto-compute version from parent lineage ───────────────────
        from sqlalchemy import select

        from loom.models import ContextUnit

        if parent_ids:
            parents = (
                await self.session.execute(
                    select(ContextUnit.version).where(
                        ContextUnit.id.in_(
                            [uuid.UUID(pid) for pid in parent_ids]
                        )
                    )
                )
            ).scalars().all()
            version = max(parents) + 1 if parents else 1
        else:
            version = 1

        try:
            unit, is_new = await write_context(
                self.session,
                self.project_id,
                self.agent_id,
                client_uuid=client_uuid,
                type_=type_,
                content=content,
                version=version,
                trust_tier=None,      # service defaults to "agent"
                parent_ids=parent_ids,
                parent_relations=parent_relations,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        return {
            "id": str(unit.id),
            "client_uuid": str(unit.client_uuid),
            "created_at": unit.created_at.isoformat() if unit.created_at else "",
            "is_new": is_new,
        }


class GetProjectSummaryTool(MCPTool):
    """Get a high-level project summary for onboarding."""

    name = "get_project_summary"
    description = (
        "Get a high-level summary of the project state. "
        "Useful for new agents joining an in-progress project or for "
        "quick status checks. Returns summary-type context units only."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Target project UUID (uses current project if omitted)",
            },
        },
        "required": [],
    }

    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        _ = args  # project_id is accepted but we use the bound one
        try:
            result = await read_context(
                self.session,
                self.project_id,
                self.agent_id,
                query=None,
                budget=8192,
                scope="onboarding",
            )
        except ValueError as exc:
            return {"error": str(exc)}

        return result


# ── Registry ──────────────────────────────────────────────────────────────────


class ToolRegistry:
    """Holds and dispatches MCP tool calls for a session+project+agent.

    Usage::

        registry = ToolRegistry(session, project_id, agent_id)
        tools = registry.list_tools()          # → MCP tool definitions
        result = registry.call("read_context", {"task_description": "..."})
    """

    def __init__(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> None:
        self.session = session
        self.project_id = project_id
        self.agent_id = agent_id

        self._tools: list[MCPTool] = [
            ReadContextTool(session, project_id, agent_id),
            WriteContextTool(session, project_id, agent_id),
            GetProjectSummaryTool(session, project_id, agent_id),
        ]
        self._tool_map: dict[str, MCPTool] = {t.name: t for t in self._tools}

    def list_tools(self) -> list[dict[str, Any]]:
        """Return MCP tool definitions for all registered tools."""
        return [t.definition() for t in self._tools]

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call by name.

        Returns a dict with either the expected result fields or an ``"error"``
        key on failure.
        """
        tool = self._tool_map.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}
        return await tool.call(args)
