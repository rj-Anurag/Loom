"""Merge repository-local terminal capture hooks without replacing user entries."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from loom.cli.project_config import load_repository_binding


class CaptureInstallError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaptureInstallError(
            f"Invalid JSON in {path}; repair it before installing capture"
        ) from exc
    if not isinstance(value, dict):
        raise CaptureInstallError(f"Expected a JSON object in {path}")
    return value


def _merged_hooks(path: Path, harness: str) -> tuple[dict[str, Any], bool]:
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise CaptureInstallError(f"Invalid hooks in {path}")
    changed = False
    for event in ("UserPromptSubmit", "Stop"):
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise CaptureInstallError(f"Invalid {event} hooks in {path}")
        if any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("hooks"), list)
            or any(not isinstance(hook, dict) for hook in entry["hooks"])
            for entry in entries
        ):
            raise CaptureInstallError(f"Malformed {event} hook in {path}; repair it and retry")
        expected = {
            "hooks": [{"type": "command", "command": f"loom capture event {harness}", "timeout": 5}]
        }
        matching = [entry for entry in entries if entry == expected]
        conflicts = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and any(
                isinstance(hook, dict) and "loom capture event" in str(hook.get("command", ""))
                for hook in entry.get("hooks", [])
                if isinstance(entry.get("hooks"), list)
            )
            and entry != expected
        ]
        if conflicts or len(matching) > 1:
            raise CaptureInstallError(f"Conflicting Loom hook in {path}; remove it and retry")
        if not matching:
            entries.append(expected)
            changed = True
    return data, changed


PLUGIN = """import { spawn } from "node:child_process";

export const LoomCapture = async ({ client, directory }) => ({
  event: async ({ event }) => {
    if (event.type !== "session.idle") return;
    const id = event.properties?.sessionID;
    if (!id) return;
    try {
      const [session, messages] = await Promise.all([
        client.session.get({ path: { id } }),
        client.session.messages({ path: { id } }),
      ]);
      if (session.data?.parentID) return;
      const payload = {
        cwd: directory,
        session_id: id,
        session_title: session.data?.title,
        messages: (messages.data ?? [])
          .filter(({ info }) => info.role === "user" ||
            (info.role === "assistant" && info.finish === "stop"))
          .map(({ info, parts }) => ({
          id: info.id,
          role: info.role,
          finish: info.finish,
          occurred_at: info.time?.created
            ? new Date(info.time.created).toISOString() : undefined,
          parts: parts.filter((part) => part.type === "text")
            .map(({ type, text }) => ({ type, text })),
        })),
      };
      const child = spawn("loom", ["capture", "event", "opencode"], {
        cwd: directory, stdio: ["pipe", "ignore", "ignore"],
      });
      child.on("error", (error) => console.error("Loom capture:", error.message));
      child.stdin.on("error", (error) => console.error("Loom capture:", error.message));
      child.stdin.end(JSON.stringify(payload));
    } catch (error) {
      console.error("Loom capture:", error.message);
    }
  },
});
"""


def prepare(root: Path, targets: set[str]) -> list[tuple[Path, str]]:
    binding, path = load_repository_binding(start=root)
    if not binding or path != root / ".loom/project.json":
        raise CaptureInstallError(f"Bind {root} with `loom init` before installing capture")
    minimums = {"codex": (0, 160, 0), "claude": (2, 1, 206), "opencode": (1, 18, 34)}
    for harness in targets:
        executable = shutil.which("claude" if harness == "claude" else harness)
        if not executable or not Path(executable).exists():
            continue
        try:
            result = subprocess.run(
                [executable, "--version"], text=True, capture_output=True, timeout=5, check=True
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CaptureInstallError(f"Cannot check {harness} version for capture") from exc
        match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout + result.stderr)
        if not match or tuple(map(int, match.groups())) < minimums[harness]:
            required = ".".join(map(str, minimums[harness]))
            raise CaptureInstallError(
                f"{harness} capture requires version {required}+; upgrade and rerun install"
            )
    prepared: list[tuple[Path, str]] = []
    for harness, relative in (("codex", ".codex/hooks.json"), ("claude", ".claude/settings.json")):
        if harness not in targets:
            continue
        target = root / relative
        data, changed = _merged_hooks(target, harness)
        if changed:
            prepared.append((target, json.dumps(data, indent=2) + "\n"))
    if "opencode" in targets:
        target = root / ".opencode/plugins/loom.js"
        if target.exists() and target.read_text(encoding="utf-8") != PLUGIN:
            raise CaptureInstallError(f"Conflicting Loom plugin in {target}; remove it and retry")
        if not target.exists():
            prepared.append((target, PLUGIN))
    return prepared
