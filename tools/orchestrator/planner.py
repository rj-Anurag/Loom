"""Planner adapter stub."""

from typing import Any

from tools.orchestrator.core import add_node, make_node


def planner_run(state: dict[str, Any], task_desc: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task": task_desc or "sample task",
        "targets": [
            {"path": "src/sample_module.py", "summary": "Add sample module with hello()"}
        ],
    }
    node = make_node("plan", payload)
    add_node(state, node)
    return node
