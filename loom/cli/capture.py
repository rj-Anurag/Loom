"""Protected, best-effort terminal conversation capture."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from loom.cli.project_config import (
    ProjectConfigError,
    load_repository_binding,
    load_saved_project,
    repository_root,
)

SOURCES = {"codex": "codex_cli", "claude": "claude_code", "opencode": "opencode"}
NAMESPACE = uuid.UUID("ed7a171e-83bb-42af-b0b5-56faf8eefdb8")


def capture_home() -> Path:
    return Path(os.environ.get("LOOM_CONFIG_HOME") or Path.home() / ".loom")


def repository_config(start: Path | None = None) -> tuple[dict[str, str], Path]:
    binding, path = load_repository_binding(start=start)
    if path is None or not binding:
        raise ProjectConfigError("Terminal capture requires this repository's .loom/project.json")
    root = path.parent.parent.resolve()
    current = (start or Path.cwd()).resolve()
    if current != root and root not in current.parents:
        raise ProjectConfigError("Capture event is outside the bound repository")
    if repository_root(start=current) != root:
        raise ProjectConfigError("Terminal capture requires the current repository's binding")
    return binding, root


def _connect() -> sqlite3.Connection:
    home = capture_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    path = home / "capture.db"
    connection = sqlite3.connect(path, timeout=5)
    os.chmod(path, 0o600)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS delivery (
        client_uuid TEXT PRIMARY KEY, project_id TEXT NOT NULL, api_url TEXT NOT NULL,
        payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT ''
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS capture_state (
        project_id TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0,
        last_upload TEXT NOT NULL DEFAULT ''
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS session_turns (
        project_id TEXT NOT NULL, source TEXT NOT NULL, session_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL DEFAULT 0, last_user_uuid TEXT,
        PRIMARY KEY(project_id, source, session_id)
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS delivered (
        client_uuid TEXT PRIMARY KEY
    )""")
    return connection


def message_uuid(project_id: str, source: str, session_id: str, identity: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{project_id}\0{source}\0{session_id}\0{identity}")


def _is_paused(connection: sqlite3.Connection, project_id: str) -> bool:
    row = connection.execute(
        "SELECT paused FROM capture_state WHERE project_id = ?", (project_id,)
    ).fetchone()
    return bool(row and row[0])


def enqueue(
    binding: dict[str, str],
    source: str,
    session_id: str,
    message: dict[str, Any],
    *,
    capture_method: str = "live",
) -> bool:
    with _connect() as connection:
        if _is_paused(connection, binding["project_id"]):
            return False
        if connection.execute(
            "SELECT 1 FROM delivered WHERE client_uuid = ?", (message["client_uuid"],)
        ).fetchone():
            return False
        payload = {
            "source_type": source,
            "source_session_id": session_id,
            "capture_method": capture_method,
            "messages": [message],
        }
        inserted = connection.execute(
            "INSERT OR IGNORE INTO delivery (client_uuid, project_id, api_url, payload) "
            "VALUES (?, ?, ?, ?)",
            (
                message["client_uuid"],
                binding["project_id"],
                binding["api_url"],
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    return inserted.rowcount > 0


def flush(*, force: bool = False, limit: int = 100) -> tuple[int, int]:
    """Upload due messages; successful response and removal share a local transaction."""
    now = datetime.now(UTC)
    uploaded = 0
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        query = (
            "SELECT client_uuid, project_id, api_url, payload, attempts FROM delivery "
            + ("" if force else "WHERE next_attempt <= ? ")
            + "ORDER BY rowid LIMIT ?"
        )
        rows = connection.execute(query, (limit,) if force else (now.isoformat(), limit)).fetchall()
        for client_uuid, project_id, api_url, payload, attempts in rows:
            saved = load_saved_project(api_url, project_id)
            key = saved.get("api_key") or (
                os.environ.get("LOOM_API_KEY")
                if os.environ.get("LOOM_PROJECT_ID") == project_id
                else None
            )
            if not key:
                error = "No saved project credential"
            else:
                try:
                    response = httpx.post(
                        f"{api_url}/v1/projects/{project_id}/conversations/messages",
                        content=payload.encode("utf-8"),
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                        },
                        timeout=2,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    error = f"HTTP {exc.response.status_code}"
                except httpx.HTTPError as exc:
                    error = type(exc).__name__
                else:
                    connection.execute("DELETE FROM delivery WHERE client_uuid = ?", (client_uuid,))
                    connection.execute(
                        "INSERT OR IGNORE INTO delivered (client_uuid) VALUES (?)", (client_uuid,)
                    )
                    connection.execute(
                        "INSERT INTO capture_state (project_id, last_upload) VALUES (?, ?) "
                        "ON CONFLICT(project_id) DO UPDATE SET last_upload = excluded.last_upload",
                        (project_id, now.isoformat()),
                    )
                    uploaded += 1
                    continue
            delay = min(3600, 2 ** min(attempts + 1, 11))
            connection.execute(
                "UPDATE delivery SET attempts = attempts + 1, next_attempt = ?, error = ? "
                "WHERE client_uuid = ?",
                ((now + timedelta(seconds=delay)).isoformat(), error, client_uuid),
            )
        pending = connection.execute("SELECT count(*) FROM delivery").fetchone()[0]
    return uploaded, pending


def flush_all() -> tuple[int, int]:
    """Drain available rows, stopping when the server cannot make progress."""
    total = 0
    while True:
        uploaded, pending = flush(force=True)
        total += uploaded
        if not uploaded or not pending:
            return total, pending


def status(project_id: str) -> dict[str, Any]:
    with _connect() as connection:
        state = connection.execute(
            "SELECT paused, last_upload FROM capture_state WHERE project_id = ?", (project_id,)
        ).fetchone()
        pending = connection.execute(
            "SELECT count(*) FROM delivery WHERE project_id = ?", (project_id,)
        ).fetchone()[0]
        errors = [
            row[0]
            for row in connection.execute(
                "SELECT error FROM delivery WHERE project_id = ? AND error != '' "
                "ORDER BY rowid DESC LIMIT 5",
                (project_id,),
            )
        ]
    return {
        "enabled": not bool(state and state[0]),
        "pending": pending,
        "last_upload": state[1] if state else None,
        "errors": errors,
    }


def set_paused(project_id: str, paused: bool) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO capture_state (project_id, paused) VALUES (?, ?) "
            "ON CONFLICT(project_id) DO UPDATE SET paused = excluded.paused",
            (project_id, int(paused)),
        )


def _claude_turn(project_id: str, session_id: str, role: str) -> tuple[str, str | None, int]:
    """Assign separate stable IDs to identical prompts in one Claude session."""
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT turn_number, last_user_uuid FROM session_turns "
            "WHERE project_id = ? AND source = 'claude_code' AND session_id = ?",
            (project_id, session_id),
        ).fetchone()
        number = row[0] if row else 0
        parent = row[1] if row else None
        if role == "user":
            number += 1
            parent = str(message_uuid(project_id, "claude_code", session_id, f"turn:{number}:user"))
            connection.execute(
                "INSERT INTO session_turns (project_id, source, session_id, turn_number, "
                "last_user_uuid) VALUES (?, 'claude_code', ?, ?, ?) "
                "ON CONFLICT(project_id, source, session_id) DO UPDATE SET "
                "turn_number = excluded.turn_number, last_user_uuid = excluded.last_user_uuid",
                (project_id, session_id, number, parent),
            )
            return parent, None, number * 2
        assistant_uuid = str(
            message_uuid(project_id, "claude_code", session_id, f"turn:{number}:assistant")
        )
        return assistant_uuid, parent, number * 2 + 1


def capture_hook(harness: str, event: dict[str, Any]) -> bool:
    source = SOURCES[harness]
    if event.get("agent_id") or event.get("agent_type") or event.get("isSidechain"):
        return False
    cwd = event.get("cwd") or str(Path.cwd())
    binding, _ = repository_config(Path(cwd))
    with _connect() as connection:
        if _is_paused(connection, binding["project_id"]):
            return False
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return False
    if harness == "opencode":
        return capture_opencode(event, binding)
    kind = event.get("hook_event_name")
    role = "user" if kind == "UserPromptSubmit" else "assistant" if kind == "Stop" else None
    if role is None or (role == "assistant" and event.get("stop_hook_active")):
        return False
    content = event.get("prompt" if role == "user" else "last_assistant_message")
    if not isinstance(content, str) or not content.strip():
        return False
    turn_id = event.get("turn_id")
    if harness == "claude" and not turn_id:
        client_id, parent_id, sequence = _claude_turn(binding["project_id"], session_id, role)
    else:
        identity = f"{turn_id}:{role}" if turn_id else f"{role}:{uuid.uuid5(NAMESPACE, content)}"
        client_id = str(message_uuid(binding["project_id"], source, session_id, identity))
        parent_id = (
            str(message_uuid(binding["project_id"], source, session_id, f"{turn_id}:user"))
            if turn_id and role == "assistant"
            else None
        )
        sequence = 0 if role == "user" else 1
    message = {
        "client_uuid": client_id,
        "role": role,
        "content": content,
        "occurred_at": datetime.now(UTC).isoformat(),
        "turn_id": turn_id,
        "message_id": None,
        "sequence": sequence,
        "session_title": event.get("session_title"),
        "parent_client_uuid": parent_id,
    }
    queued = enqueue(binding, source, session_id, message)
    flush(limit=1)
    return queued


def capture_opencode(event: dict[str, Any], binding: dict[str, str]) -> bool:
    """Store only completed root-session text parts exported by the plugin."""
    session_id = event["session_id"]
    if event.get("parent_id") or not isinstance(event.get("messages"), list):
        return False
    queued = False
    last_user_uuid: str | None = None
    for index, item in enumerate(event["messages"]):
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
            continue
        if item.get("role") == "assistant" and item.get("finish") not in {"stop", "completed"}:
            continue
        parts = item.get("parts")
        if not isinstance(parts, list):
            continue
        content = "\n".join(
            part["text"]
            for part in parts
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ).strip()
        if not content:
            continue
        message_id = item.get("id")
        if not isinstance(message_id, str) or not message_id:
            continue
        client_uuid = str(message_uuid(binding["project_id"], "opencode", session_id, message_id))
        role = item["role"]
        if role == "user":
            last_user_uuid = client_uuid
        timestamp = item.get("occurred_at") or datetime.now(UTC).isoformat()
        message = {
            "client_uuid": client_uuid,
            "role": role,
            "content": content,
            "occurred_at": timestamp,
            "turn_id": None,
            "message_id": message_id,
            "sequence": index,
            "session_title": event.get("session_title"),
            "parent_client_uuid": last_user_uuid if role == "assistant" else None,
        }
        queued = enqueue(binding, "opencode", session_id, message) or queued
    flush(limit=1)
    return queued
