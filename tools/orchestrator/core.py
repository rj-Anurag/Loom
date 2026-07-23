"""Checkpoint graph: the core data structure for the orchestrator pipeline."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def make_node(kind: str, payload: dict[str, Any], parent: str | None = None) -> dict[str, Any]:
    node_id = str(uuid.uuid4())
    return {
        "id": node_id,
        "kind": kind,
        "payload": payload,
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
        "parent": parent,
    }


def add_node(state: dict[str, Any], node: dict[str, Any]) -> str:
    node_id: str = node["id"]
    state["nodes"][node_id] = node
    state["checkpoints"].append(node_id)
    return node_id


def create_initial_state(path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "checkpoints": [],
        "nodes": {},
    }
    save_state(path, state)
    return state


def load_state(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return dict(json.load(f))


def save_state(path: Path, state: dict[str, Any]) -> None:
    with path.open("w") as f:
        json.dump(state, f, indent=2)


def get_node(state: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    nodes: dict[str, Any] = state.get("nodes", {})
    return nodes.get(node_id)


def get_children(state: dict[str, Any], parent_id: str) -> list[dict[str, Any]]:
    return [
        n for n in state["nodes"].values()
        if n.get("parent") == parent_id
    ]


def update_status(state: dict[str, Any], node_id: str, status: str) -> None:
    if node_id in state.get("nodes", {}):
        state["nodes"][node_id]["status"] = status
