---
title: "Phase 3.2 — Authentication & Authorization"
description: "Per-agent API keys, JWT for browser sessions, project-scoped authorization, secrets management integration."
status: pending
dependencies: ["phase-1/01-db-schema.md"]
---

# Authentication & Authorization

## Description
Implement the full authentication and authorization system for Loom. Every request must be authenticated (prove identity) and authorized (prove access to the requested project/action).

## Authentication

### Agent API Keys
Each agent gets a scoped API key:
```
lom_<project_id>_<random_hex>
```

API keys are:
- Generated at registration time (agent can't choose its own)
- Hashed with bcrypt before storage
- Stored in the `agents` table (hashed)
- Never returned after initial creation (show-once)

### Registration Flow
```
POST /v1/projects/{id}/agents
Body: { "kind": "local|cloud|browser" }
Response: { "agent_id": "uuid", "api_key": "lom_...", "trust_tier": "agent" }
```

### Browser Sessions (JWT)
Browser users authenticate via email/password or OAuth:
```
POST /v1/auth/login
Body: { "email": "...", "password": "..." }
Response: { "token": "jwt...", "user_id": "uuid" }
```

JWT tokens:
- Signed with HS256 (RS256 for production)
- 24-hour expiry
- Claims: `user_id`, `project_id`, `role` (admin/member/viewer)
- Refreshed via `/v1/auth/refresh`

## Authorization

### Project-Scoped Access
Every request is scoped to a project:
1. Extract API key or JWT from `Authorization` header
2. Decode identity and project access
3. Check that the requested `project_id` matches the token's scope
4. If not authorized → 403 Forbidden

### Trust Tier Enforcement
The agent's `trust_tier` is determined by its authentication method:
| Auth Method | Max Trust Tier |
|---|---|
| JWT (user session) | `user` |
| API key (agent) | `agent` |
| External webhook key | `external_tool` |

Agents cannot write above their max trust tier (enforced in middleware).

### Role-Based Access (Users)
| Role | Permissions |
|---|---|
| `admin` | Create/delete projects, manage agents, all read/write |
| `member` | Read/write context, create tasks |
| `viewer` | Read-only access to context and events |

## Secrets Management

### What NOT to Do
- Never store API keys, passwords, or tokens in the database as plaintext
- Never log secrets or include them in error messages
- Never put secrets in source code or `.env` files committed to git

### Secrets Storage
For v1, use environment variables loaded from a secrets manager:
```python
# In production, secrets come from a secrets manager, not .env
if settings.ENVIRONMENT == "production":
    secrets = await get_secrets_from_manager(settings.SECRETS_MANAGER_URL)
else:
    secrets = dotenv_values(".env")
```

### API Key Hashing
```python
import bcrypt

def hash_api_key(api_key: str) -> str:
    return bcrypt.hashpw(api_key.encode(), bcrypt.gensalt())

def verify_api_key(api_key: str, hashed: str) -> bool:
    return bcrypt.checkpw(api_key.encode(), hashed.encode())
```

## File Targets
- `api/middleware.py` — auth middleware (extract identity, enforce trust tier)
- `api/routes/auth.py` — login, refresh, agent registration
- `services/auth/__init__.py` — auth service package
- `services/auth/service.py` — token generation, verification, key hashing
- `tests/integration/test_auth.py` — auth integration tests

## Acceptance Criteria
- [ ] API keys are generated, returned once, and hashed before storage
- [ ] Requests with valid API keys are authenticated
- [ ] Requests with invalid/missing API keys return 401
- [ ] Requests for a different project than the key allows return 403
- [ ] JWT login returns a valid token with correct claims
- [ ] Trust tier enforcement prevents agents from writing as `user`
- [ ] All endpoints are protected (no unauthenticated access)

## TDD Instructions
```python
@pytest.mark.asyncio
async def test_api_key_auth_success(client, test_agent_key):
    resp = await client.get("/v1/projects/test/context",
                            headers={"Authorization": f"Bearer {test_agent_key}"})
    assert resp.status_code in (200, 404)  # 404 if project doesn't exist, but auth passed

@pytest.mark.asyncio
async def test_api_key_auth_failure(client):
    resp = await client.get("/v1/projects/test/context",
                            headers={"Authorization": "Bearer invalid-key"})
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_trust_tier_enforcement(client, test_agent_key):
    # Agent with agent-tier key cannot write as user
    resp = await client.post("/v1/projects/test/context", json={
        "client_uuid": str(uuid4()),
        "type": "message",
        "content": "test",
        "trust_tier": "user",
        "version": 1
    }, headers={"Authorization": f"Bearer {test_agent_key}"})
    assert resp.status_code == 403
```

## Dependencies
- Phase 1.1 (agents table with credentials_ref)
