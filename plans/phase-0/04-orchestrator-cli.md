---
title: "Phase 0.4 — Orchestrator CLI"
description: "Python CLI tool for the checkpoint-graph build pipeline: Planner -> Coder -> Test Runner -> Fixer -> Reviewer."
status: completed
framework: "Python argparse CLI + JSON checkpoint graph"
dependencies: ["phase-0/01-project-scaffold.md"]
---

# Orchestrator CLI

## Description
Build the Python CLI tool that orchestrates the agentic TDD pipeline. It manages a checkpoint graph stored as JSON, tracks every step (plan, code change, test run, fix, review), and supports resume from any node.

## Location
All code goes under `tools/orchestrator/`.

## Core Concepts

- **Checkpoint graph**: JSON file storing nodes as a DAG. Each node has: `id`, `kind`, `payload`, `status`, `created_at`, `parent`.
- **Single-file change policy**: Each coder node modifies exactly one logical change.
- **Adapters**: Pluggable LLM-backed adapters for Planner, Coder, Reviewer; executable adapters for Test Runner; LLM adapter for Fixer.
- **Retry policy**: Fixer retries capped at N (configurable, default 3). Test runner is deterministic.

## Files to Create

### `tools/orchestrator/__init__.py`
Package init, exports main classes.

### `tools/orchestrator/core.py`
Core data structures:
- `CheckpointGraph` class — load/save state JSON, add_node, get_node, get_children, get_parent
- `make_node(kind, payload, parent)` — factory function
- `load_state(path)`, `save_state(path, state)` — file I/O helpers

### `tools/orchestrator/cli.py`
CLI using `argparse`:
- `plan <task>` — create initial checkpoint with plan node
- `run --step planner|coder|test|fixer|reviewer --node <id>` — execute one step
- `status` — print current state
- `resume --from <node_id>` — resume pipeline from a specific node
- `graph` — print the checkpoint graph as a tree

### `tools/orchestrator/planner.py`
Planner adapter (stub initially):
- Takes high-level task, returns structured plan with subtasks
- Each subtask has: file path, summary, acceptance criteria, dependencies

### `tools/orchestrator/coder.py`
Coder adapter (stub initially):
- Takes a single file change instruction, applies it as a patch
- Records the diff in the checkpoint

### `tools/orchestrator/test_runner.py`
Test runner adapter:
- Executes `pytest`, `ruff`, `mypy` commands
- Parses stdout/stderr into structured results
- Returns pass/fail with failure details

### `tools/orchestrator/fixer.py`
Fixer adapter (stub initially):
- Consumes test failure output + last diff
- Produces a fix specification
- Tracks retry count in checkpoint

### `tools/orchestrator/reviewer.py`
Reviewer adapter (stub initially):
- Reads the diff and original spec
- Returns structured review (approve/changes-requested/blocked)

### `tools/orchestrator/state.json`
Default state file (gitignored, created on first run).

## CLI Usage

```bash
# Plan a feature
python -m tools.orchestrator.cli plan "Implement login button"

# Run each step
python -m tools.orchestrator.cli run --step planner
python -m tools.orchestrator.cli run --step coder
python -m tools.orchestrator.cli run --step test

# Check status
python -m tools.orchestrator.cli status

# Resume from a failed node
python -m tools.orchestrator.cli resume --from <node_id>
```

## Acceptance Criteria

- [ ] `python -m tools.orchestrator.cli plan "test"` creates `state.json` with a plan node
- [ ] `python -m tools.orchestrator.cli status` prints valid JSON
- [ ] `python -m tools.orchestrator.cli run --step planner` executes planner stub
- [ ] `python -m tools.orchestrator.cli run --step test` runs pytest and returns results
- [ ] Checkpoint graph correctly tracks parent-child relationships
- [ ] Resume from any node reproduces the same state
- [ ] All adapters are pluggable (can be replaced by config)

## TDD Instructions

**Before implementing:** Write tests for the core checkpoint graph:

```python
def test_make_node_creates_node_with_id():
    node = make_node("plan", {"task": "test"})
    assert node["id"] is not None
    assert node["kind"] == "plan"

def test_add_node_appends_to_state():
    state = {"nodes": {}, "checkpoints": []}
    node = make_node("plan", {"task": "test"})
    add_node(state, node)
    assert node["id"] in state["nodes"]
    assert node["id"] in state["checkpoints"]

def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    state = create_initial_state(path)
    loaded = load_state(path)
    assert loaded["nodes"] == {}
```

Write these tests first, then implement `core.py` to make them pass.

## Dependencies
- Phase 0.1 (project scaffold — directory structure must exist)
