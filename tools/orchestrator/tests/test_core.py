"""Tests for the orchestrator checkpoint graph."""

from pathlib import Path
from typing import Any

from tools.orchestrator.core import (
    add_node,
    create_initial_state,
    get_children,
    get_node,
    load_state,
    make_node,
    update_status,
)


def test_make_node_creates_node_with_id() -> None:
    node = make_node("plan", {"task": "test"})
    assert node["id"] is not None
    assert node["kind"] == "plan"
    assert node["status"] == "pending"
    assert node["parent"] is None


def test_make_node_with_parent() -> None:
    parent = make_node("plan", {"task": "parent"})
    child = make_node("coder", {"file": "test.py"}, parent=parent["id"])
    assert child["parent"] == parent["id"]


def test_add_node_appends_to_state() -> None:
    state: dict[str, Any] = {"nodes": {}, "checkpoints": []}
    node = make_node("plan", {"task": "test"})
    add_node(state, node)
    assert node["id"] in state["nodes"]
    assert node["id"] in state["checkpoints"]


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = create_initial_state(path)
    assert state["nodes"] == {}
    assert "created_at" in state
    loaded = load_state(path)
    assert loaded == state


def test_create_initial_writes_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = create_initial_state(path)
    assert path.exists()
    assert state["checkpoints"] == []


def test_get_node_returns_none_for_missing() -> None:
    state: dict[str, Any] = {"nodes": {}}
    assert get_node(state, "nonexistent") is None


def test_get_node_returns_node() -> None:
    state: dict[str, Any] = {"nodes": {}, "checkpoints": []}
    node = make_node("plan", {"task": "x"})
    add_node(state, node)
    result = get_node(state, node["id"])
    assert result is not None
    assert result["kind"] == "plan"


def test_get_children() -> None:
    state: dict[str, Any] = {"nodes": {}, "checkpoints": []}
    parent = make_node("plan", {})
    add_node(state, parent)
    child1 = make_node("coder", {}, parent=parent["id"])
    child2 = make_node("coder", {}, parent=parent["id"])
    add_node(state, child1)
    add_node(state, child2)
    children = get_children(state, parent["id"])
    assert len(children) == 2


def test_update_status() -> None:
    state: dict[str, Any] = {"nodes": {}, "checkpoints": []}
    node = make_node("plan", {})
    add_node(state, node)
    update_status(state, node["id"], "completed")
    updated = state["nodes"][node["id"]]
    assert updated["status"] == "completed"


def test_update_status_ignores_missing() -> None:
    state: dict[str, Any] = {"nodes": {}}
    update_status(state, "nonexistent", "completed")
    assert True  # no crash
