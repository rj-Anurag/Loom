import tomllib
from pathlib import Path


def test_package_imports():
    import loom  # noqa: F401

    assert True


def test_pyproject_is_valid_toml():
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert "project" in data
    assert data["project"]["name"] == "loom"


def test_runtime_assets_are_included_in_distribution():
    with open(Path(__file__).parent.parent / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)

    package_data = data["tool"]["setuptools"]["package-data"]["loom"]
    assert "web/**/*.html" in package_data
    assert "web/**/*.css" in package_data
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
