---
title: "Phase 2.4 — Redis Live Presence"
description: "Agent heartbeat and status tracking in Redis. Live view of active agents, their current tasks, and lock management for the extension sidebar."
status: completed
dependencies: ["phase-2/01-full-coordination.md"]
---

# Redis Live Presence

## Description
Track which agents are currently active, what they're working on, and their status via Redis. This enables the live "who's working" view in the extension sidebar and provides heartbeat-based dead agent detection.

## Data Model

### Agent Heartbeat
```python
async def record_heartbeat(agent_id: str, project_id: str, status: str, task_id: str = None):
    """Record an agent heartbeat with current status."""
    key = f"presence:agent:{agent_id}"
    await redis.hset(key, mapping={
        "agent_id": agent_id,
        "project_id": project_id,
        "status": status,  # "idle" | "working" | "blocked" | "offline"
        "task_id": task_id or "",
        "last_seen": datetime.utcnow().isoformat(),
        "ip_address": get_agent_ip(agent_id)
    })
    await redis.expire(key, 60)  # Expire if no heartbeat for 60s
```

### Agent List by Project
```python
async def get_active_agents(project_id: str) -> list[dict]:
    """Get all active agents in a project."""
    keys = await redis.keys(f"presence:agent:*")
    agents = []
    for key in keys:
        data = await redis.hgetall(key)
        if data.get("project_id") == project_id:
            agents.append(data)
    return agents
```

## Heartbeat Protocol
- Agents send a heartbeat every 15 seconds via the API
- `POST /v1/agents/{id}/heartbeat`
- If no heartbeat for 60 seconds, agent is marked as "offline"
- Locks held by offline agents are released (after grace period)

### Heartbeat Endpoint
```
POST /v1/agents/{agent_id}/heartbeat
Body: { "status": "working|idle|blocked", "task_id": "optional-uuid" }
Response: 200 OK
```

## Live Presence in Extension Sidebar
The browser extension sidebar shows:
- Connected agents and their status
- Agent names/types
- What task each agent is working on
- How long since last heartbeat

### WebSocket Events
```
event: agent_online     → { agent_id, kind, status }
event: agent_heartbeat  → { agent_id, status, task_id }
event: agent_offline    → { agent_id }
event: agent_lock       → { agent_id, context_unit_id }
event: agent_unlock     → { agent_id, context_unit_id }
```

## Lock Monitoring
Track which locks are held by which agent:
```python
async def get_active_locks(project_id: str) -> list[dict]:
    """Get all active locks in a project."""
    lock_keys = await redis.keys(f"lock:context_unit:*")
    locks = []
    for key in lock_keys:
        holder = await redis.get(key)
        ttl = await redis.ttl(key)
        context_unit_id = key.replace("lock:context_unit:", "")
        locks.append({
            "context_unit_id": context_unit_id,
            "held_by": holder,
            "ttl_seconds": ttl
        })
    return locks
```

## File Targets
- `api/routes/agents.py` — heartbeat endpoint
- `services/coordination/presence.py` — presence tracking logic
- `services/coordination/lock_monitor.py` — lock monitoring
- `api/websocket/handler.py` — add presence events to broadcast

## Acceptance Criteria
- [ ] Agent heartbeat is recorded in Redis
- [ ] Heartbeat expiry marks agent as offline
- [ ] Browser UI shows active agents with status
- [ ] Offline agents are detected within 60 seconds
- [ ] Locks held by offline agents are released
- [ ] Heartbeat endpoint is authenticated
- [ ] Presence data survives Redis restart (re-heartbeat)

## TDD Instructions
```python
@pytest.mark.asyncio
async def test_heartbeat_records_presence(client, test_agent):
    resp = await client.post(f"/v1/agents/{test_agent}/heartbeat",
                             json={"status": "working"})
    assert resp.status_code == 200
    presence = await redis.hgetall(f"presence:agent:{test_agent}")
    assert presence["status"] == "working"

@pytest.mark.asyncio
async def test_heartbeat_expiry(redis_client, test_agent):
    await record_heartbeat(test_agent, "project-1", "working")
    # Wait for expiry
    await asyncio.sleep(61)
    exists = await redis.exists(f"presence:agent:{test_agent}")
    assert not exists
```

## Dependencies
- Phase 2.1 (Redis lock infrastructure)
