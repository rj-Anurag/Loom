"""Secure local storage for project-scoped CLI agent credentials."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPOSITORY_CONFIG = Path(".loom/project.json")


class ProjectConfigError(ValueError):
    """Raised when a repository binding exists but is invalid or unusable."""


@dataclass(frozen=True)
class ResolvedProjectConfig:
    api_url: str
    project_id: str
    project_name: str
    api_key: str
    source: str
    descriptor_path: Path | None = None


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


def load_current_api_url(*, path: Path | None = None) -> str:
    """Return the active API server saved in the local Loom configuration."""
    target = path or project_config_path()
    data = _read(target)
    current = data.get("current_server_url")
    if isinstance(current, str) and current:
        return current.rstrip("/")
    servers = data.get("servers", {})
    if isinstance(servers, dict) and len(servers) == 1:
        return str(next(iter(servers))).rstrip("/")
    return ""


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


def load_saved_project(
    api_url: str,
    project_id: str,
    *,
    path: Path | None = None,
) -> dict[str, str]:
    """Load one saved project without relying on the server's active project."""
    target = path or project_config_path()
    data = _read(target)
    servers = data.get("servers", {})
    server = servers.get(api_url.rstrip("/"), {}) if isinstance(servers, dict) else {}
    projects = server.get("projects", {}) if isinstance(server, dict) else {}
    project = projects.get(project_id, {}) if isinstance(projects, dict) else {}
    if not isinstance(project, dict):
        return {}
    return {
        "project_id": project_id,
        "project_name": str(project.get("name") or ""),
        "api_key": str(project.get("api_key") or ""),
    }


def find_repository_binding(*, start: Path | None = None) -> Path | None:
    """Find the nearest repository binding at or above ``start``."""
    current = (start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / REPOSITORY_CONFIG
        if candidate.is_file():
            return candidate
    return None


def load_repository_binding(
    *,
    start: Path | None = None,
) -> tuple[dict[str, str], Path | None]:
    """Read the nearest commit-safe repository descriptor."""
    path = find_repository_binding(start=start)
    if path is None:
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectConfigError(f"Invalid Loom repository binding: {path}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ProjectConfigError(f"Unsupported Loom repository binding: {path}")
    required = ("api_url", "project_id", "project_name")
    if any(not isinstance(data.get(field), str) or not data[field] for field in required):
        raise ProjectConfigError(f"Incomplete Loom repository binding: {path}")
    return {field: str(data[field]) for field in required}, path


def repository_root(*, start: Path | None = None) -> Path:
    """Return the nearest VCS root, falling back to the starting directory."""
    current = (start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        if (directory / ".git").exists():
            return directory
    return current


def save_repository_binding(
    api_url: str,
    *,
    project_id: str,
    project_name: str,
    root: Path | None = None,
) -> Path:
    """Atomically save a non-secret project binding in the repository."""
    target = (root or repository_root()) / REPOSITORY_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "api_url": api_url.rstrip("/"),
        "project_id": project_id,
        "project_name": project_name,
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=".project-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def resolve_project_config(*, start: Path | None = None) -> ResolvedProjectConfig:
    """Resolve one coherent project selection and its matching credential."""
    binding, binding_path = load_repository_binding(start=start)
    env_url = os.environ.get("LOOM_API_URL", "").rstrip("/")
    env_project_id = os.environ.get("LOOM_PROJECT_ID", "")
    env_api_key = os.environ.get("LOOM_API_KEY", "")

    if env_project_id:
        api_url = env_url or binding.get("api_url") or load_current_api_url()
        saved = load_saved_project(api_url, env_project_id) if api_url else {}
        return ResolvedProjectConfig(
            api_url=api_url or "http://localhost:8000",
            project_id=env_project_id,
            project_name=saved.get("project_name", ""),
            api_key=env_api_key or saved.get("api_key", ""),
            source="environment",
            descriptor_path=binding_path,
        )

    if (
        binding
        and binding_path is not None
        and (not env_url or env_url == binding["api_url"].rstrip("/"))
    ):
        api_url = env_url or binding["api_url"].rstrip("/")
        saved = load_saved_project(api_url, binding["project_id"])
        if not env_api_key and not saved.get("api_key"):
            raise ProjectConfigError(
                f"Repository {binding_path.parent.parent} is bound to project "
                f"{binding['project_id']}, but its credential is not saved. "
                "Run `loom login` and `loom switch " + binding["project_id"] + "`."
            )
        return ResolvedProjectConfig(
            api_url=api_url,
            project_id=binding["project_id"],
            project_name=binding["project_name"],
            api_key=env_api_key or saved.get("api_key", ""),
            source="environment" if env_url or env_api_key else "repository",
            descriptor_path=binding_path,
        )

    api_url = env_url or load_current_api_url() or "http://localhost:8000"
    current = load_current_project(api_url)
    return ResolvedProjectConfig(
        api_url=api_url,
        project_id=current.get("project_id", ""),
        project_name=current.get("project_name", ""),
        api_key=env_api_key or current.get("api_key", ""),
        source="environment" if env_url or env_api_key else "global",
        descriptor_path=binding_path,
    )


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
    data["current_server_url"] = server_key

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
