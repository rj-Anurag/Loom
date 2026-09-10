"""Secure local storage for project-scoped CLI agent credentials."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def project_config_path() -> Path:
    root = os.environ.get("LOOM_CONFIG_HOME")
    return (
        Path(root).expanduser() / "projects.json"
        if root
        else Path.home() / ".loom/projects.json"
    )


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return {"servers": {}}
    return data if isinstance(data, dict) else {"servers": {}}


def load_current_project(api_url: str, *, path: Path | None = None) -> dict[str, str]:
    target = path or project_config_path()
    data = _read(target)
    servers = data.get("servers", {})
    server = servers.get(api_url.rstrip("/"), {}) if isinstance(servers, dict) else {}
    current_id = server.get("current_project_id") if isinstance(server, dict) else None
    projects = server.get("projects", {}) if isinstance(server, dict) else {}
    project = projects.get(current_id, {}) if isinstance(projects, dict) and current_id else {}
    if not isinstance(project, dict):
        return {}
    return {
        "project_id": str(current_id),
        "project_name": str(project.get("name") or ""),
        "api_key": str(project.get("api_key") or ""),
    }


def save_project(
    api_url: str,
    *,
    project_id: str,
    project_name: str,
    api_key: str,
    path: Path | None = None,
) -> None:
    target = path or project_config_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target.parent, 0o700)
    data = _read(target)
    servers = data.setdefault("servers", {})
    if not isinstance(servers, dict):
        servers = {}
        data["servers"] = servers
    server_key = api_url.rstrip("/")
    server = servers.setdefault(server_key, {"projects": {}})
    if not isinstance(server, dict):
        server = {"projects": {}}
        servers[server_key] = server
    projects = server.setdefault("projects", {})
    if not isinstance(projects, dict):
        projects = {}
        server["projects"] = projects
    projects[project_id] = {"name": project_name, "api_key": api_key}
    server["current_project_id"] = project_id

    descriptor, temporary_name = tempfile.mkstemp(prefix=".projects-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
