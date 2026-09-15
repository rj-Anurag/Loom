import tomllib
from pathlib import Path

import pytest


def test_package_imports():
    import loom  # noqa: F401

    assert True


def test_pyproject_is_valid_toml():
    from loom import __version__

    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert "project" in data
    assert data["project"]["name"] == "loom"
    assert data["project"]["version"] == __version__


def test_package_declares_supported_desktop_platforms_and_urls():
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        project = tomllib.load(f)["project"]

    classifiers = project["classifiers"]
    assert "Operating System :: MacOS" in classifiers
    assert "Operating System :: Microsoft :: Windows" in classifiers
    assert "Operating System :: POSIX :: Linux" in classifiers
    assert project["urls"]["Repository"] == "https://github.com/rj-Anurag/Loom.git"


def test_cli_exposes_the_package_version(capsys):
    from loom import __version__
    from loom.cli.main import build_parser

    with pytest.raises(SystemExit) as result:
        build_parser().parse_args(["--version"])

    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == f"loom {__version__}"


def test_runtime_assets_are_included_in_distribution():
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    package_data = data["tool"]["setuptools"]["package-data"]["loom"]
    assert not any(asset.startswith("web/") for asset in package_data)
    assert "services/context/migrations/*.sql" in package_data


def test_local_embedding_stack_is_optional():
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    assert not any(
        dependency.startswith("sentence-transformers")
        for dependency in data["project"]["dependencies"]
    )
    assert data["project"]["optional-dependencies"]["local-embeddings"] == [
        "sentence-transformers>=3.0.0"
    ]
