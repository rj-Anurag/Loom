"""Deterministic agent stubs with shaped content for merge/conflict demo.

Content is carefully designed so that:
- Agent A and Agent B write about *disjoint* entities (auto-merge).
- Agent C's third write deliberately overlaps with Agent A (conflict).

See ``plans/phase-2/06-multi-agent-demo.md`` for the full scenario.
"""

from __future__ import annotations

from typing import Any

from agents.demo.base import DemoAgent


class PasswordAgent(DemoAgent):
    """Agent A (Local) — designs password hashing.

    Writes about ``src/auth/hash.py``, ``bcrypt``, ``def hash_password``.
    These entities are NOT referenced by Agent B (auto-merge).
    """

    def _content_for_step(
        self, step: int, task: str, context: list[dict[str, Any]]
    ) -> str:
        steps = [
            "Decision: Use bcrypt for password hashing in `src/auth/hash.py`. "
            "Reasoning: bcrypt includes built-in salt and configurable cost factor.",
            "Implementation: Add `import hashlib` — actually use `import bcrypt` "
            "in `src/auth/hash.py`. Salt rounds = 12.",
            "Detail: Define `def hash_password(password: str) -> str` using "
            "`bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))`. "
            "Add `def verify_password(password: str, hash: str) -> bool`.",
        ]
        return steps[step] if step < len(steps) else steps[-1]


class SessionAgent(DemoAgent):
    """Agent B (Cloud) — designs session management.

    Writes about ``src/auth/session.py``, ``jwt``, ``def create_token``.
    These entities are disjoint from Agent A (auto-merge possible).
    """

    def _content_for_step(
        self, step: int, task: str, context: list[dict[str, Any]]
    ) -> str:
        steps = [
            "Decision: Use JWT for session tokens in `src/auth/session.py`. "
            "Reasoning: Stateless, no server-side storage needed.",
            "Implementation: Add `import jwt` and `import datetime` in "
            "`src/auth/session.py`. Use HS256 with 24h expiry.",
            "Detail: Define `def create_token(user_id: str) -> str` with "
            "`jwt.encode({'user_id': user_id, 'exp': datetime.utcnow() + "
            "timedelta(hours=24)}, key, algorithm='HS256')`.",
        ]
        return steps[step] if step < len(steps) else steps[-1]


class LoginFormAgent(DemoAgent):
    """Agent C (Browser) — designs the login form UI.

    First 2 steps write about ``src/auth/login.html`` (disjoint from A/B).
    Step 3 deliberately references ``def hash_password`` — an entity
    already used by Agent A — to trigger conflict detection.
    """

    def _content_for_step(
        self, step: int, task: str, context: list[dict[str, Any]]
    ) -> str:
        steps = [
            "Design: Login form in `src/auth/login.html` with email + password "
            "fields. Form uses POST to `/auth/login`. Include CSRF token.",
            "Styling: CSS for login form — centered card layout, 400px max-width, "
            "brand color #4f46e5 for primary button.",
            "Integration: The login form handler calls `def hash_password` from "
            "`src/auth/hash.py` to verify credentials. This entity is shared "
            "with the password agent (overlap). "
            "Also references `def create_token` from `src/auth/session.py`.",
        ]
        return steps[step] if step < len(steps) else steps[-1]
