#!/usr/bin/env python
"""Orchestrator CLI — manages the checkpoint-graph build pipeline.

Usage:
  python -m tools.orchestrator.cli plan <task>
  python -m tools.orchestrator.cli run --step <planner|coder|test|fixer|reviewer>
  python -m tools.orchestrator.cli status
  python -m tools.orchestrator.cli resume --from <node_id>
  python -m tools.orchestrator.cli graph
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.orchestrator.coder import coder_apply
from tools.orchestrator.core import (
    create_initial_state,
    get_children,
    get_node,
    load_state,
    save_state,
)
from tools.orchestrator.fixer import fixer_run
from tools.orchestrator.planner import planner_run
from tools.orchestrator.reviewer import reviewer_run
from tools.orchestrator.test_runner import run_tests

STATE_PATH = Path("tools/orchestrator/state.json")

STEPS: dict[str, Any] = {
    "planner": planner_run,
    "coder": coder_apply,
    "test": run_tests,
    "fixer": fixer_run,
    "reviewer": reviewer_run,
}


def ensure_state() -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        return create_initial_state(STATE_PATH)
    return load_state(STATE_PATH)


def cmd_plan(args: argparse.Namespace) -> None:
    state = ensure_state()
    planner_run(state, args.task)
    save_state(STATE_PATH, state)
    print(f"Planned: {args.task}")


def cmd_run(args: argparse.Namespace) -> None:
    state = ensure_state()
    step_fn = STEPS.get(args.step)
    if not step_fn:
        print(f"Unknown step: {args.step}")
        sys.exit(1)
    step_fn(state)
    save_state(STATE_PATH, state)
    print(f"Step '{args.step}' executed.")


def cmd_status(args: argparse.Namespace) -> None:
    state = ensure_state()
    summary = {
        "checkpoint_count": len(state["checkpoints"]),
        "node_count": len(state["nodes"]),
        "nodes": state["nodes"],
    }
    print(json.dumps(summary, indent=2))


def cmd_resume(args: argparse.Namespace) -> None:
    state = ensure_state()
    node = get_node(state, args.node_id)
    if not node:
        print(f"Node not found: {args.node_id}")
        sys.exit(1)
    print(f"Resuming from node: {node['id']} ({node['kind']}, status={node['status']})")


def cmd_graph(args: argparse.Namespace) -> None:
    state = ensure_state()
    roots = [n for n in state["nodes"].values() if n.get("parent") is None]

    def print_tree(node: dict[str, Any], indent: int = 0) -> None:
        prefix = "  " * indent
        print(f"{prefix}* {node['kind']}:{node['id'][:8]} ({node['status']})")
        for child in get_children(state, node["id"]):
            print_tree(child, indent + 1)

    for root in roots:
        print_tree(root)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="orchestrator", description="Checkpoint-graph build pipeline"
    )
    sub = parser.add_subparsers(dest="cmd")

    p_plan = sub.add_parser("plan", help="Create a new plan checkpoint")
    p_plan.add_argument("task", help="High-level task description")

    p_run = sub.add_parser("run", help="Execute a pipeline step")
    p_run.add_argument("--step", choices=list(STEPS), required=True)
    p_run.add_argument("--node", help="Node ID to run (optional)")

    sub.add_parser("status", help="Show current pipeline state")

    p_resume = sub.add_parser("resume", help="Resume from a specific node")
    p_resume.add_argument("--from", dest="node_id", required=True, help="Node ID to resume from")

    sub.add_parser("graph", help="Print the checkpoint graph as a tree")

    args = parser.parse_args()
    if args.cmd == "plan":
        cmd_plan(args)
    elif args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "status":
        cmd_status(args)
    elif args.cmd == "resume":
        cmd_resume(args)
    elif args.cmd == "graph":
        cmd_graph(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
