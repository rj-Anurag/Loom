from __future__ import annotations

from pathlib import Path

import pytest

from loom.cli.project_config import (
    ProjectConfigError,
    load_current_api_url,
    load_current_project,
    resolve_project_config,
    save_project,
    save_repository_binding,
)


def test_project_credentials_are_saved_outside_dotenv_by_default(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"

    save_project(
        "https://loom.example.com",
        project_id="project-a",
        project_name="Project A",
        api_key="loom_secret",
        path=path,
    )

    current = load_current_project("https://loom.example.com", path=path)
    assert current == {
        "project_id": "project-a",
        "project_name": "Project A",
        "api_key": "loom_secret",
    }
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_current_api_url(path=path) == "https://loom.example.com"


def test_project_credentials_are_scoped_by_server(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    save_project(
        "https://one.example.com",
        project_id="one",
        project_name="One",
        api_key="loom_one",
        path=path,
    )
    save_project(
        "https://two.example.com",
        project_id="two",
        project_name="Two",
        api_key="loom_two",
        path=path,
    )

    assert load_current_project("https://one.example.com", path=path)["project_id"] == "one"
    assert load_current_project("https://two.example.com", path=path)["project_id"] == "two"
    assert load_current_api_url(path=path) == "https://two.example.com"


def test_mcp_uses_saved_active_server_without_environment(monkeypatch, tmp_path: Path) -> None:
    from loom.mcp.server import _api_key, _api_url, _project_id

    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("LOOM_API_URL", raising=False)
    monkeypatch.delenv("LOOM_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_PROJECT_ID", raising=False)
    save_project(
        "https://loom.example.com",
        project_id="project-a",
        project_name="Project A",
        api_key="loom_secret",
    )

    assert _api_url() == "https://loom.example.com"
    assert _project_id() == "project-a"
    assert _api_key() == "loom_secret"


def test_repository_binding_selects_matching_project(monkeypatch, tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    repo_one = tmp_path / "repo-one"
    repo_two = tmp_path / "repo-two"
    repo_one.mkdir()
    repo_two.mkdir()
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(config_home))
    monkeypatch.delenv("LOOM_API_URL", raising=False)
    monkeypatch.delenv("LOOM_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_PROJECT_ID", raising=False)

    save_project(
        "https://loom.example.com",
        project_id="one",
        project_name="One",
        api_key="loom_one",
    )
    save_project(
        "https://loom.example.com",
        project_id="two",
        project_name="Two",
        api_key="loom_two",
    )
    save_repository_binding(
        "https://loom.example.com",
        project_id="one",
        project_name="One",
        root=repo_one,
    )
    save_repository_binding(
        "https://loom.example.com",
        project_id="two",
        project_name="Two",
        root=repo_two,
    )

    first = resolve_project_config(start=repo_one / "nested")
    second = resolve_project_config(start=repo_two)
    assert (first.project_id, first.api_key, first.source) == (
        "one",
        "loom_one",
        "repository",
    )
    assert (second.project_id, second.api_key, second.source) == (
        "two",
        "loom_two",
        "repository",
    )


def test_repository_binding_never_falls_back_to_wrong_credential(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("LOOM_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("LOOM_API_URL", raising=False)
    monkeypatch.delenv("LOOM_API_KEY", raising=False)
    monkeypatch.delenv("LOOM_PROJECT_ID", raising=False)
    save_project(
        "https://loom.example.com",
        project_id="other",
        project_name="Other",
        api_key="loom_other",
    )
    save_repository_binding(
        "https://loom.example.com",
        project_id="missing",
        project_name="Missing",
        root=repo,
    )

    with pytest.raises(ProjectConfigError, match="credential is not saved"):
        resolve_project_config(start=repo)
