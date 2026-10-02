"""Explicit, preview-first import of supported terminal session histories."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loom.cli.capture import SOURCES, enqueue, flush_all, message_uuid


def _within(path: str | None, root: Path) -> bool:
    if not path:
        return False
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        return False
    resolved = candidate.resolve()
    return resolved == root or root in resolved.parents


def _text_parts(parts: object) -> str:
    if isinstance(parts, str):
        return parts.strip()
    if not isinstance(parts, list):
        return ""
    return "\n".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict)
        and part.get("type") in {"text", "input_text", "output_text"}
        and isinstance(part.get("text"), str)
    ).strip()


def _codex_records(path: Path, root: Path) -> list[dict[str, Any]]:
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if isinstance(item, dict):
                records.append(item)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    metadata: dict[str, Any] = next(
        (item.get("payload", {}) for item in records if item.get("type") == "session_meta"), {}
    )
    if not _within(metadata.get("cwd"), root):
        return []
    if metadata.get("thread_source") not in (None, "user"):
        return []
    has_user_items = any(
        item.get("type") == "response_item"
        and isinstance(item.get("payload"), dict)
        and item["payload"].get("type") == "message"
        and item["payload"].get("role") == "user"
        for item in records
    )
    messages: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if (
            not has_user_items
            and record.get("type") == "event_msg"
            and payload.get("type") == "user_message"
        ):
            role, content = "user", payload.get("message")
        elif (
            record.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "user"
        ):
            role, content = "user", _text_parts(payload.get("content"))
        elif (
            record.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "assistant"
            and payload.get("phase") in {"final", "final_answer"}
        ):
            role, content = "assistant", _text_parts(payload.get("content"))
        else:
            continue
        if isinstance(content, str) and content.strip():
            messages.append(
                {
                    "id": str(index),
                    "role": role,
                    "content": content.strip(),
                    "occurred_at": record.get("timestamp"),
                }
            )
    return [{"session_id": metadata.get("id") or path.stem, "messages": messages}]


def _claude_records(path: Path, root: Path) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    session_id = path.stem
    matched = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            item = json.loads(line)
            if not isinstance(item, dict) or item.get("isSidechain"):
                continue
            matched = matched or _within(item.get("cwd"), root)
            if item.get("type") not in {"user", "assistant"}:
                continue
            raw = item.get("message")
            if not isinstance(raw, dict):
                continue
            if item["type"] == "assistant" and raw.get("stop_reason") not in {
                "end_turn",
                "stop_sequence",
            }:
                continue
            content = _text_parts(raw.get("content"))
            if content:
                messages.append(
                    {
                        "id": item.get("uuid") or str(index),
                        "role": item["type"],
                        "content": content,
                        "occurred_at": item.get("timestamp"),
                    }
                )
            session_id = item.get("sessionId") or session_id
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    return [{"session_id": session_id, "messages": messages}] if matched else []


def _opencode_records(root: Path) -> list[dict[str, Any]]:
    executable = shutil.which("opencode")
    if not executable:
        return []
    try:
        listing = subprocess.run(
            [executable, "session", "list", "--format", "json"],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=15,
            check=True,
        )
        sessions = json.loads(listing.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    if not isinstance(sessions, list):
        return []
    result = []
    for session in sessions:
        if (
            not isinstance(session, dict)
            or session.get("parentID")
            or not _within(session.get("directory"), root)
        ):
            continue
        session_id = session.get("id")
        if not isinstance(session_id, str):
            continue
        try:
            exported = subprocess.run(
                [executable, "export", session_id],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=15,
                check=True,
            )
            data = json.loads(exported.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("info"), dict) and data["info"].get("parentID"):
            continue
        messages = []
        for index, item in enumerate(data.get("messages", [])):
            if not isinstance(item, dict):
                continue
            info = item.get("info") or {}
            if info.get("role") not in {"user", "assistant"}:
                continue
            if info.get("role") == "assistant" and info.get("finish") not in {"stop", "completed"}:
                continue
            content = _text_parts(item.get("parts"))
            if content:
                created = info.get("time", {}).get("created")
                timestamp = (
                    datetime.fromtimestamp(created / 1000, UTC).isoformat()
                    if isinstance(created, (int, float))
                    else None
                )
                messages.append(
                    {
                        "id": info.get("id") or str(index),
                        "role": info["role"],
                        "content": content,
                        "occurred_at": timestamp,
                    }
                )
        result.append(
            {"session_id": session_id, "title": session.get("title"), "messages": messages}
        )
    return result


def preview(
    harness: str, binding: dict[str, str], root: Path, session_filter: str | None = None
) -> list[tuple[str, str, dict[str, Any]]]:
    """Return candidate messages without writing the local queue or API."""
    harnesses = SOURCES if harness == "all" else {harness: SOURCES[harness]}
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for name, source in harnesses.items():
        if name == "opencode":
            sessions = _opencode_records(root)
        else:
            base = Path.home() / (".codex/sessions" if name == "codex" else ".claude/projects")
            reader = _codex_records if name == "codex" else _claude_records
            sessions = (
                [record for path in base.rglob("*.jsonl") for record in reader(path, root)]
                if base.exists()
                else []
            )
        for session in sessions:
            session_id = session["session_id"]
            if session_filter and session_id != session_filter:
                continue
            last_user: str | None = None
            for index, item in enumerate(session["messages"]):
                role = item["role"]
                message_id = str(item["id"])
                client_uuid = str(
                    message_uuid(binding["project_id"], source, session_id, f"import:{message_id}")
                )
                if role == "user":
                    last_user = client_uuid
                message = {
                    "client_uuid": client_uuid,
                    "role": role,
                    "content": item["content"],
                    "occurred_at": item.get("occurred_at") or datetime.now(UTC).isoformat(),
                    "turn_id": None,
                    "message_id": message_id,
                    "sequence": index,
                    "session_title": session.get("title"),
                    "parent_client_uuid": last_user if role == "assistant" else None,
                }
                candidates.append((source, session_id, message))
    return candidates


def apply(candidates: list[tuple[str, str, dict[str, Any]]], binding: dict[str, str]) -> int:
    queued = sum(
        enqueue(binding, source, session_id, message, capture_method="import")
        for source, session_id, message in candidates
    )
    flush_all()
    return queued
