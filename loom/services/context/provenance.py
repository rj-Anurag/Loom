"""Validation and defaults for context provenance and structured metadata."""

from __future__ import annotations

import json
from typing import Any

SOURCE_TYPES = frozenset(
    {
        "browser_chat",
        "codex_cli",
        "claude_code",
        "opencode",
        "manual_cli",
        "dashboard",
        "mcp_agent",
    }
)

_DEFAULT_SOURCE_BY_AGENT_KIND = {
    "browser": "browser_chat",
    "local": "mcp_agent",
    "cloud": "mcp_agent",
    "system": "mcp_agent",
}

_ALLOWED_SOURCES_BY_AGENT_KIND = {
    "browser": {"browser_chat"},
    "local": {"codex_cli", "claude_code", "opencode", "manual_cli", "mcp_agent"},
    "cloud": {"codex_cli", "claude_code", "opencode", "mcp_agent"},
    "system": {"dashboard", "mcp_agent"},
}

_LIST_FIELDS = ("files_touched", "errors", "blockers", "next_steps")
_TEST_STATUSES = {"passed", "failed", "not_run"}
_MAX_METADATA_BYTES = 65_536
_MAX_LIST_ITEMS = 200
_MAX_TEXT_LENGTH = 4_096
METADATA_FIELDS = frozenset(
    {"task_name", "files_touched", "tests", "errors", "blockers", "next_steps", "confidence"}
)


def resolve_source_type(agent_kind: str, requested: str | None) -> str:
    """Return a validated source type for an authenticated agent kind."""
    source_type = requested or _DEFAULT_SOURCE_BY_AGENT_KIND.get(agent_kind, "mcp_agent")
    if source_type not in SOURCE_TYPES:
        raise ValueError("INVALID_SOURCE_TYPE")
    allowed = _ALLOWED_SOURCES_BY_AGENT_KIND.get(agent_kind, {"mcp_agent"})
    if source_type not in allowed:
        raise ValueError("SOURCE_TYPE_DENIED")
    return source_type


def validate_context_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the bounded, JSON-compatible task-result metadata shape."""
    metadata = dict(value or {})
    try:
        encoded = json.dumps(metadata, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("INVALID_METADATA_JSON") from exc
    if len(encoded) > _MAX_METADATA_BYTES:
        raise ValueError("METADATA_TOO_LARGE")
    if unknown := set(metadata) - METADATA_FIELDS:
        raise ValueError("INVALID_METADATA_FIELDS:" + ",".join(sorted(unknown)))

    task_name = metadata.get("task_name")
    if task_name is not None and (
        not isinstance(task_name, str)
        or not task_name.strip()
        or len(task_name) > 500
    ):
        raise ValueError("INVALID_TASK_NAME")
    for field in _LIST_FIELDS:
        if field not in metadata:
            continue
        items = metadata[field]
        if (
            not isinstance(items, list)
            or len(items) > _MAX_LIST_ITEMS
            or any(
                not isinstance(item, str) or len(item) > _MAX_TEXT_LENGTH
                for item in items
            )
        ):
            raise ValueError(f"INVALID_METADATA_{field.upper()}")

    if "tests" in metadata:
        tests = metadata["tests"]
        if not isinstance(tests, list) or len(tests) > _MAX_LIST_ITEMS:
            raise ValueError("INVALID_METADATA_TESTS")
        for test in tests:
            if not isinstance(test, dict):
                raise ValueError("INVALID_METADATA_TESTS")
            if set(test) - {"command", "status", "summary"}:
                raise ValueError("INVALID_METADATA_TESTS")
            if (
                not isinstance(test.get("command"), str)
                or not test["command"].strip()
                or len(test["command"]) > _MAX_TEXT_LENGTH
            ):
                raise ValueError("INVALID_METADATA_TESTS")
            if test.get("status") not in _TEST_STATUSES:
                raise ValueError("INVALID_METADATA_TESTS")
            if "summary" in test and (
                not isinstance(test["summary"], str)
                or len(test["summary"]) > _MAX_TEXT_LENGTH
            ):
                raise ValueError("INVALID_METADATA_TESTS")

    confidence = metadata.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not 0 <= float(confidence) <= 1
    ):
        raise ValueError("INVALID_METADATA_CONFIDENCE")
    return metadata


def metadata_from_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Build validated metadata from the shared MCP write argument names."""
    return validate_context_metadata(
        {key: arguments[key] for key in METADATA_FIELDS if arguments.get(key) is not None}
    )
