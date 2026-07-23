"""Coder adapter stub — applies a single file change."""

from typing import Any

from tools.orchestrator.core import add_node, make_node


def coder_apply(state: dict[str, Any], instruction: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = instruction or {
        "file": "src/sample_module.py",
        "change": "Add hello() function",
    }
    node = make_node("coder", payload)
    add_node(state, node)
    return node
