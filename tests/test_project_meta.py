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
