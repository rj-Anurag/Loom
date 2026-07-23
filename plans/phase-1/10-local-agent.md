---
title: "Phase 1.10 — Local Agent Prototype"
description: "A Python agent that runs on the developer's machine, authenticates with Loom, reads context, runs an LLM call, and writes results back."
status: pending
dependencies: ["phase-1/05-mcp-tools.md", "phase-1/06-idempotency.md"]
---

# Local Agent Prototype

## Description
Build a working local agent that demonstrates the full read-LM-write loop. This is the "hello world" of Loom — proving that an agent can read shared context, process it with an LLM, and write the result back through the MCP tools.

## Location
`agents/local/agent.py`

## How It Works

```
1. Agent starts, authenticates with Loom
2. Agent calls read_context(task_description="Build a login feature")
3. Agent receives relevant context units (spec, existing decisions, prior work)
4. Agent calls an LLM (Anthropic API) with: system prompt + retrieved context
5. LLM produces a result (e.g., "Use bcrypt for password hashing")
6. Agent calls write_context(content=result, type="decision", parent_ids=[...])
7. Agent logs the success and exits
```

## Implementation Details

### Configuration
```python
# agents/local/config.py
LOOM_API_URL = os.getenv("LOOM_API_URL", "http://localhost:8000")
LOOM_API_KEY = os.getenv("LOOM_API_KEY", "dev-agent-key")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEFAULT_PROJECT_ID = os.getenv("LOOM_PROJECT_ID")
```

### Agent Main Loop
```python
async def run_agent(task_description: str, project_id: str):
    # 1. Read context
    context = await read_context(
        task_description=task_description,
        token_budget=4096
    )

    # 2. Build LLM prompt
    prompt = build_prompt(task_description, context["units"])

    # 3. Call LLM
    response = await call_llm(prompt)

    # 4. Write result
    result = await write_context(
        content=response,
        type="task_result",
        parent_ids=[u["id"] for u in context["units"]],
        parent_relations=["derived_from"] * len(context["units"])
    )

    print(f"Wrote context unit: {result['id']}")
    return result
```

### LLM Integration
```python
async def call_llm(prompt: str):
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system="You are an AI agent working in a multi-agent collaboration system. "
               "Read the provided context and complete the task. "
               "Write your result as a clear, structured response.",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text
```

### CLI Entry Point
The agent should be runnable from the command line:
```bash
python -m agents.local.agent --task "Design the authentication flow" --project <id>
```

## Demo Task
The agent should be able to complete this toy task:
```
"Review the project context and write a decision about what
 authentication method to use for the Loom API."
```

## File Targets
- `agents/local/__init__.py`
- `agents/local/agent.py` — main agent loop
- `agents/local/config.py` — configuration
- `tests/integration/test_local_agent.py` — end-to-end test

## Acceptance Criteria

- [ ] Agent starts, authenticates, and reads context
- [ ] Agent calls an LLM and gets a response
- [ ] Agent writes the response as a context unit
- [ ] The written context unit is visible via the read API
- [ ] `client_uuid` is generated and retry-safe
- [ ] Agent handles errors gracefully (LLM timeout, API down)

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_agent_read_write_loop(test_project, test_agent_config):
    agent = LocalAgent(config=test_agent_config)
    result = await agent.run("Write a test decision")
    assert result is not None
    assert "id" in result

@pytest.mark.asyncio
async def test_agent_written_context_is_readable(client, test_project, test_agent_config):
    agent = LocalAgent(config=test_agent_config)
    await agent.run("Write a test decision")
    resp = await client.get(f"/v1/projects/{test_project}/context?query=test")
    assert len(resp.json()["units"]) > 0
```

## Dependencies
- Phase 1.5 (MCP tools must work)
- Phase 1.6 (idempotent writes)
- Anthropic API key (external dependency — set in .env)
