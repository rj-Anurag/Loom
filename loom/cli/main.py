"""@loom CLI — interact with the Loom context layer from the terminal.

Usage::

    loom context "what was decided about auth"
    loom write "Decision: use bcrypt for passwords"
    loom init
    loom mcp
    loom projects

Configuration via environment variables or ``.env`` file:

- ``LOOM_API_URL`` — Loom API base URL (default ``http://localhost:8000``)
- ``LOOM_API_KEY`` — Agent bearer token (Agent UUID)
- ``LOOM_PROJECT_ID`` — Project UUID
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import uuid

import httpx

from loom.cli.dotenv import load_dotenv
from loom.mcp.server import main as mcp_main

load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────────


def _api_url() -> str:
    return os.environ.get("LOOM_API_URL", "http://localhost:8000").rstrip("/")


def _api_key() -> str:
    return os.environ.get("LOOM_API_KEY", "")


def _project_id() -> str:
    return os.environ.get("LOOM_PROJECT_ID", "")


def _headers() -> dict[str, str]:
    key = _api_key()
    return {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}


def _check_project_config() -> None:
    """Exit with error if required config is missing."""
    missing: list[str] = []
    if not _api_key():
        missing.append("LOOM_API_KEY")
    if not _project_id():
        missing.append("LOOM_PROJECT_ID")
    if missing:
        print(
            f"Error: Missing {', '.join(missing)}.\n"
            f"Run `loom init` to create a project and get credentials.",
            file=sys.stderr,
        )
        sys.exit(1)


def _format_unit(u: dict) -> str:
    """Format a single context unit for CLI display."""
    score = u.get("relevance_score", 0)
    lines = [
        f"[{u.get('type', '?')}] relevance={score:.2f}",
        f"  agent: {u.get('agent_id', '?')[:8]}...",
        f"  created: {u.get('created_at', '?')[:19]}",
        f"  version: {u.get('version', 1)}",
    ]
    content = u.get("content", "")
    if len(content) > 500:
        content = content[:500] + "..."
    lines.append(f"  content: {textwrap.shorten(content, width=200, placeholder='...')}")
    return "\n".join(lines)


# ── Subcommands ───────────────────────────────────────────────────────────────


def cmd_context(args: argparse.Namespace) -> None:
    """Fetch context relevant to a query from the Loom project."""
    _check_project_config()

    resp = httpx.get(
        f"{_api_url()}/v1/projects/{_project_id()}/context",
        params={
            "query": args.query,
            "budget": args.budget,
            "scope": args.scope,
        },
        headers=_headers(),
        timeout=30,
    )

    if resp.status_code == 401:
        print("Error: Authentication failed. Check LOOM_API_KEY.", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 404:
        print("Error: Project not found. Check LOOM_PROJECT_ID.", file=sys.stderr)
        sys.exit(1)
    resp.raise_for_status()

    data = resp.json()
    units = data.get("units", [])

    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return

    if not units:
        print("No relevant context found.")
        return

    print(
        f"Found {len(units)} context unit(s) "
        f"(budget: {data.get('budget_used', '?')}/{args.budget} tokens):\n"
    )
    for i, u in enumerate(units, 1):
        print(f"─── Unit {i} ───")
        print(_format_unit(u))
        print()


def cmd_write(args: argparse.Namespace) -> None:
    """Write a context unit to the Loom project."""
    _check_project_config()

    if not args.content and sys.stdin.isatty() is False:
        args.content = sys.stdin.read().strip()

    if not args.content:
        print("Error: No content provided. Pass content as an argument or pipe it in.", file=sys.stderr)
        sys.exit(1)

    body: dict = {
        "client_uuid": str(uuid.uuid4()),
        "type": args.type,
        "content": args.content,
        "version": args.version,
    }

    resp = httpx.post(
        f"{_api_url()}/v1/projects/{_project_id()}/context",
        json=body,
        headers=_headers(),
        timeout=30,
    )

    if resp.status_code == 401:
        print("Error: Authentication failed. Check LOOM_API_KEY.", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 404:
        print("Error: Project not found. Check LOOM_PROJECT_ID.", file=sys.stderr)
        sys.exit(1)
    if resp.status_code == 409:
        detail = resp.json()
        print(
            f"Version conflict: current={detail.get('current_version', '?')}, "
            f"claimed={detail.get('claimed_version', '?')}.\n"
            "Read latest context first, then retry with a higher version.",
            file=sys.stderr,
        )
        sys.exit(1)
    resp.raise_for_status()

    data = resp.json()
    status = "created" if resp.status_code == 201 else "idempotent replay"
    print(f"✅ Context unit {data.get('id', '?')[:8]}... {status} (version={data.get('version', args.version)})")


def cmd_init(args: argparse.Namespace) -> None:
    """Create a new project + agent and print configuration.

    Calls the ``/v1/extension/setup`` endpoint to bootstrap a project
    and returns the credentials needed for ``LOOM_API_KEY`` and
    ``LOOM_PROJECT_ID``.
    """
    url = _api_url()
    print(f"Setting up Loom project via {url}/v1/extension/setup ...")

    resp = httpx.get(f"{url}/v1/extension/setup", timeout=30)
    resp.raise_for_status()
    data = resp.json()

    project_id = data["id"]
    project_name = data["name"]
    api_key = data["api_key"]

    print(f"\n✅ Project created: {project_name} ({project_id})\n")
    print("Add these to your shell profile or .env file:\n")
    print(f"  export LOOM_API_URL={url}")
    print(f"  export LOOM_API_KEY={api_key}")
    print(f"  export LOOM_PROJECT_ID={project_id}")
    print()

    # Optionally write to .env
    if args.write_env:
        env_path = args.write_env
        with open(env_path, "a") as f:
            f.write(f"\n# Loom — added by `loom init`\n")
            f.write(f"LOOM_API_URL={url}\n")
            f.write(f"LOOM_API_KEY={api_key}\n")
            f.write(f"LOOM_PROJECT_ID={project_id}\n")
        print(f"✅ Written to {env_path}")


def cmd_projects(args: argparse.Namespace) -> None:
    """List all projects (requires auth)."""
    if not _api_key():
        print("Error: LOOM_API_KEY is required to list projects.", file=sys.stderr)
        sys.exit(1)

    resp = httpx.get(
        f"{_api_url()}/v1/projects",
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    projects = resp.json()

    if args.json:
        print(json.dumps(projects, indent=2, default=str))
        return

    if not projects:
        print("No projects found.")
        return

    print(f"{'ID':<40} {'Name':<30} {'Created':<20}")
    print("-" * 90)
    for p in projects:
        pid = p.get("id", "")[:36]
        name = p.get("name", "")
        created = (p.get("created_at") or "")[:19]
        print(f"{pid:<40} {name:<30} {created:<20}")


def cmd_config(args: argparse.Namespace) -> None:
    """Show current Loom CLI configuration."""
    print(f"LOOM_API_URL    = {_api_url()}")
    print(f"LOOM_API_KEY    = {_api_key()[:8] + '...' if _api_key() else '(not set)'}")
    print(f"LOOM_PROJECT_ID = {_project_id() or '(not set)'}")


# ── CLI Entry Point ───────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loom",
        description="@loom CLI — interact with the Loom context layer",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # loom context
    p_context = sub.add_parser("context", help="Fetch context relevant to a query")
    p_context.add_argument("query", help="Natural-language query for context retrieval")
    p_context.add_argument("--budget", type=int, default=4096, help="Token budget (default 4096)")
    p_context.add_argument("--scope", choices=["onboarding", "task", "full"], default="task", help="Context scope")
    p_context.add_argument("--json", action="store_true", help="Output raw JSON")

    # loom write
    p_write = sub.add_parser("write", help="Write a context unit")
    p_write.add_argument("content", nargs="?", help="Content to write (omit to pipe from stdin)")
    p_write.add_argument("--type", default="task_result", help="Unit type (default: task_result)")
    p_write.add_argument("--version", type=int, default=1, help="Version number (default: 1)")
    p_write.add_argument("--json", action="store_true", help="Output raw JSON")

    # loom init
    p_init = sub.add_parser("init", help="Create a new project and get credentials")
    p_init.add_argument("--write-env", metavar="PATH", nargs="?", const=".env", help="Write config to .env file (default: .env)")

    # loom projects
    p_projects = sub.add_parser("projects", help="List all projects")
    p_projects.add_argument("--json", action="store_true", help="Output raw JSON")

    # loom config
    sub.add_parser("config", help="Show current configuration")

    # loom mcp
    sub.add_parser("mcp", help="Start the MCP stdio server (for AI CLI tools)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    COMMANDS = {
        "context": cmd_context,
        "write": cmd_write,
        "init": cmd_init,
        "projects": cmd_projects,
        "config": cmd_config,
        "mcp": lambda _: mcp_main(),
    }

    handler = COMMANDS.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
