from __future__ import annotations

from pathlib import Path

from loom.cli.project_config import load_current_project, save_project


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
