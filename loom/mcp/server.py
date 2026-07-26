"""Loom MCP Server — exposes read/write context as Model Context Protocol tools.

Usage (stdio transport — default for MCP)::

    # Start the server (for AI CLI tools to connect to)
    LOOM_API_URL=http://localhost:8000 \\
    LOOM_API_KEY=your-agent-uuid \\
    LOOM_PROJECT_ID=your-project-uuid \\
    python -m loom.mcp.server

Configuration via environment variables:

- ``LOOM_API_URL`` — Loom API base URL (default ``http://localhost:8000``)
- ``LOOM_API_KEY`` — Agent bearer token (Agent UUID).
- ``LOOM_PROJECT_ID`` — Project UUID to scope all operations.

The server implements the Model Context Protocol (MCP) over stdio,
which is the standard transport for CLI AI tools like Claude Code
and opencode.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx
from mcp.server.fastmcp import Context, FastMCP

# ── Configuration (lazy — read from env on each call) ─────────────────────────


def _api_url() -> str:
    return os.environ.get("LOOM_API_URL", "http://localhost:8000").rstrip("/")


def _api_key() -> str:
    return os.environ.get("LOOM_API_KEY", "")


def _project_id() -> str:
    return os.environ.get("LOOM_PROJECT_ID", "")


def _check_config() -> None:
    """Raise ``ValueError`` if required config is missing."""
    missing: list[str] = []
    if not _api_key():
        missing.append("LOOM_API_KEY")
    if not _project_id():
        missing.append("LOOM_PROJECT_ID")
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Run `loom init` to create a project and agent, or set them manually."
        )


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_api_key()}",
    }


def _http_client() -> httpx.AsyncClient:
    """Create an AsyncClient bound to the configured API URL."""
    return httpx.AsyncClient(base_url=_api_url())


# ── MCP Server ───────────────────────────────────────────────────────────────

mcp = FastMCP(
    "Loom",
    instructions="Loom Context Server — shared persistent context for AI agents. "
    "Provides read_context, write_context, and get_project_summary tools.",
)


@mcp.tool(description=(
    "Search and retrieve context units from the Loom project "
    "that are relevant to a given query. "
    "Use this when you need background information, past decisions, "
    "or any previously stored context to answer the user's question. "
    "Results are ranked by relevance and packed to fit the token budget."
))
async def read_context(
    query: str,
    budget: int = 4096,
    scope: str = "task",
) -> str:
    """Read relevant context units from the shared Loom project.

    Parameters
    ----------
    query : str
        Natural-language description of what context you need.
    budget : int
        Maximum token budget for returned context (default 4096, max 32000).
    scope : str
        Scope filter: "task" (default, all types), "onboarding" (summaries
        only), or "full" (everything).

    Returns
    -------
    str
        Formatted context units with relevance scores and metadata.
        Returns "No relevant context found." when the project is empty
        or no units match the query.
    """
    _check_config()
    async with _http_client() as client:
        resp = await client.get(
            f"/v1/projects/{_project_id()}/context",
            params={"query": query, "budget": budget, "scope": scope},
            headers=_headers(),
        )
        if resp.status_code == 401:
            return "Authentication failed. Check your LOOM_API_KEY."
        if resp.status_code == 404:
            return "Project not found. Check your LOOM_PROJECT_ID."
        resp.raise_for_status()
        data = resp.json()

    units = data.get("units", [])
    if not units:
        return "No relevant context found."

    lines: list[str] = [
        f"Found {len(units)} context unit(s) "
        f"(budget: {data.get('budget_used', '?')}/{budget} tokens):",
    ]
    for u in units:
        score = u.get("relevance_score", 0)
        lines.append("")
        lines.append(f"[{u['type']}] relevance={score:.2f} | agent={u['agent_id'][:8]}...")
        lines.append(f"  {u['content']}")
        if u.get("parent_ids"):
            lines.append(f"  parents: {', '.join(p[:8] for p in u['parent_ids'])}")

    return "\n".join(lines)


@mcp.tool(description=(
    "Write a new context unit to the Loom project. "
    "Use this to store decisions, task results, summaries, "
    "or any information that should be persisted for future "
    "agents working on this project. "
    "The write is idempotent — sending the same content twice "
    "is safe and will not create duplicates."
))
async def write_context(
    content: str,
    type: str = "task_result",
    version: int = 1,
) -> str:
    """Write a context unit to the shared Loom project.

    Parameters
    ----------
    content : str
        Text content of the context unit (max 100,000 chars).
    type : str
        Unit type: "message", "decision", "artifact_ref",
        "task_result" (default), or "summary".
    version : int
        Version number (default 1). Must equal ``max(parent.version) + 1``
        if there are existing units in the project.

    Returns
    -------
    str
        Confirmation message with the new unit's ID and status.
    """
    _check_config()
    body: dict = {
        "client_uuid": str(uuid.uuid4()),
        "type": type,
        "content": content,
        "version": version,
    }
    async with _http_client() as client:
        resp = await client.post(
            f"/v1/projects/{_project_id()}/context",
            json=body,
            headers=_headers(),
        )
        if resp.status_code == 401:
            return "Authentication failed. Check your LOOM_API_KEY."
        if resp.status_code == 404:
            return "Project not found. Check your LOOM_PROJECT_ID."
        if resp.status_code == 409:
            detail = resp.json()
            return (
                f"Version conflict (current={detail.get('current_version', '?')}, "
                f"claimed={detail.get('claimed_version', '?')}). "
                "Try reading the latest context first, then retry with a higher version."
            )
        resp.raise_for_status()
        data = resp.json()

    unit_id = data.get("id", "unknown")
    status = "created" if resp.status_code == 201 else "idempotent replay"
    return f"Context unit {unit_id[:8]}... {status} (version={data.get('version', version)})"


@mcp.tool(description=(
    "Get a summary of the current Loom project. "
    "Returns the project name, ID, and recent context statistics. "
    "Use this to get an overview before diving into specific context queries."
))
async def get_project_summary() -> str:
    """Get a summary of the Loom project.

    Returns
    -------
    str
        Project name, ID, timestamps, and total context unit count.
    """
    _check_config()
    async with _http_client() as client:
        # Get project details
        resp = await client.get(
            f"/v1/projects/{_project_id()}",
            headers=_headers(),
        )
        if resp.status_code == 401:
            return "Authentication failed. Check your LOOM_API_KEY."
        if resp.status_code == 404:
            return "Project not found. Check your LOOM_PROJECT_ID."
        resp.raise_for_status()
        project = resp.json()

        # Get context count via a read with a large scope
        count_resp = await client.get(
            f"/v1/projects/{_project_id()}/context",
            params={"budget": 1, "scope": "full"},
            headers=_headers(),
        )

    count_data = count_resp.json() if count_resp.status_code == 200 else {}
    unit_count = len(count_data.get("units", []))

    return (
        f"Project: {project.get('name', 'unknown')}\n"
        f"  ID: {_project_id()}\n"
        f"  Created: {project.get('created_at', 'unknown')}\n"
        f"  Recent context units: {unit_count}"
    )


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Run the MCP server over stdio.

    This is the entry point registered in ``pyproject.toml`` and
    referenced in ``opencode.json`` / ``claude_desktop_config.json``::

        {
            "mcpServers": {
                "loom": {
                    "command": "loom",
                    "args": ["mcp"],
                    "env": {
                        "LOOM_API_URL": "http://localhost:8000",
                        "LOOM_API_KEY": "...",
                        "LOOM_PROJECT_ID": "..."
                    }
                }
            }
        }
    """
    try:
        _check_config()
    except ValueError as exc:
        import sys
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    mcp.run()


if __name__ == "__main__":
    main()
