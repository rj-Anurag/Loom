from __future__ import annotations

from pathlib import Path

from loom.cli.project_config import load_current_api_url, load_current_project, save_project


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
