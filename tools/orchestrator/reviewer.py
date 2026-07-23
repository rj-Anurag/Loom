"""Reviewer adapter stub — reviews diff and returns verdict."""

from typing import Any

from tools.orchestrator.core import add_node, make_node


def reviewer_run(
    state: dict[str, Any],
    diff_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = diff_summary or {"verdict": "approve", "issues": []}
    node = make_node("reviewer", payload)
    add_node(state, node)
    return node
