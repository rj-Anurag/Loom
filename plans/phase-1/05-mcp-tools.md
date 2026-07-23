---
title: "Phase 1.5 — MCP Tools (read_context / write_context)"
description: "Model Context Protocol tool wrappers that agents call to interact with Loom's shared context store."
status: pending
dependencies: ["phase-1/02-context-service-write.md", "phase-1/03-context-service-read.md"]
---

# MCP Tools

## Description
Create MCP (Model Context Protocol) tool definitions that any agent — local, cloud, or browser — can call to read from and write to Loom's shared context store. These are the primary interface between agents and Loom.

## Tool Definitions

### `read_context`

```python
{
    "name": "read_context",
    "description": "Retrieve relevant context from the shared project store. Returns a token-budgeted, relevance-ranked bundle of context units.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Description of what the agent is working on, used for relevance ranking"
            },
            "token_budget": {
                "type": "integer",
                "description": "Maximum tokens to return (default 4096, max 32000)",
                "default": 4096
            },
            "scope": {
                "type": "string",
                "enum": ["task", "onboarding", "full"],
                "description": "Scope of context to retrieve",
                "default": "task"
            },
            "min_trust_tier": {
                "type": "string",
                "enum": ["user", "agent", "external_tool"],
                "description": "Minimum trust tier to include",
                "default": "external_tool"
            }
        },
        "required": ["task_description"]
    }
}
```

### `write_context`

```python
{
    "name": "write_context",
    "description": "Write a new context unit to the shared project store. Results, decisions, messages, and artifact references are all written through this tool.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The content to write"
            },
            "type": {
                "type": "string",
                "enum": ["message", "decision", "artifact_ref", "task_result", "summary"],
                "description": "Type of context unit"
            },
            "parent_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "UUIDs of parent context units this derives from or references"
            },
            "parent_relations": {
                "type": "array",
                "items": {"type": "string", "enum": ["derived_from", "supersedes", "references", "merged_from"]},
                "description": "Relations to parent units (parallel array to parent_ids)"
            }
        },
        "required": ["content", "type"]
    }
}
```

### `get_project_summary`

```python
{
    "name": "get_project_summary",
    "description": "Get a high-level summary of the project state. Useful for new agents joining an in-progress project.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Project UUID"
            }
        },
        "required": ["project_id"]
    }
}
```

## Implementation

Create `services/context/mcp_tools.py` with:
- `ReadContextTool` — calls the Gateway's read endpoint with auth
- `WriteContextTool` — calls the Gateway's write endpoint with auth + client_uuid
- `GetProjectSummaryTool` — fetches summary-type context units for the project

Each tool:
- Validates input against the schema
- Handles authentication (injects API key from agent's config)
- Handles errors gracefully (returns structured error messages, not exceptions)
- Generates `client_uuid` for write operations automatically if not provided

## File Targets
- `services/context/mcp_tools.py` — tool definitions and implementations
- `services/context/__init__.py` — export tool registry

## Acceptance Criteria

- [ ] `read_context` returns context units ranked by relevance
- [ ] `write_context` creates a new context unit and returns its ID
- [ ] `write_context` is idempotent (same content + same call = same result)
- [ ] `get_project_summary` returns summary-type units for the project
- [ ] All tools properly handle auth errors
- [ ] Tools can be called from a local agent process via MCP

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_read_context_tool(mcp_tool_registry, sample_project):
    result = await mcp_tool_registry.call("read_context", {
        "task_description": "implement login feature",
        "token_budget": 1000
    })
    assert "units" in result
    assert result["total_tokens"] <= 1000

@pytest.mark.asyncio
async def test_write_context_tool(mcp_tool_registry, sample_project):
    result = await mcp_tool_registry.call("write_context", {
        "content": "Decision: use JWT for auth",
        "type": "decision"
    })
    assert "id" in result
```

## Dependencies
- Phase 1.2 (write path must work)
- Phase 1.3 (read path must work)
