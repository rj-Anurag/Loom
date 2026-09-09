"""Tests for installing and packaging Loom's Chrome extension."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from loom.cli.extension import (
    ExtensionDistributionError,
    inspect_extension,
    install_extension,
    normalize_api_url,
    package_extension,
)
from loom.cli.main import build_parser

ROOT = Path(__file__).resolve().parents[2]


def test_normalize_api_url_accepts_http_origins_and_removes_trailing_slash() -> None:
    assert normalize_api_url("https://loom.example.com/") == "https://loom.example.com"
    assert normalize_api_url("http://localhost:8000///") == "http://localhost:8000"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "loom.example.com",
        "file:///tmp/server",
        "javascript:alert(1)",
        "https://user:password@loom.example.com",
        "https://loom.example.com?token=secret",
        "https://loom.example.com/#fragment",
    ],
)
def test_normalize_api_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ExtensionDistributionError):
        normalize_api_url(value)


def test_install_extension_configures_only_the_selected_api_origin(tmp_path: Path) -> None:
    destination = tmp_path / "installed-extension"

    result = install_extension(
        api_url="https://loom.example.com/base/",
        destination=destination,
    )

    assert result.path == destination
    assert result.backup_path is None
    config = (destination / "config.js").read_text(encoding="utf-8")
    assert 'LOOM_SERVER_URL: "https://loom.example.com/base"' in config
    assert "DEFAULT_API_KEY: ''" in config

    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert "https://loom.example.com/*" in manifest["host_permissions"]
    assert "http://localhost:8000/*" not in manifest["host_permissions"]
    assert "https://loom-api-zzy0.onrender.com/*" not in manifest["host_permissions"]
    assert "https://claude.ai/*" in manifest["host_permissions"]

    status = inspect_extension(destination)
    assert status.installed is True
    assert status.manifest_valid is True
    assert status.api_url == "https://loom.example.com/base"
    assert status.host_permission is True
    assert status.credentials_embedded is False


def test_install_extension_refuses_overwrite_without_force(tmp_path: Path) -> None:
    destination = tmp_path / "installed-extension"
    destination.mkdir()
    (destination / "keep.txt").write_text("user data", encoding="utf-8")

    with pytest.raises(ExtensionDistributionError, match="already exists"):
        install_extension(api_url="https://loom.example.com", destination=destination)

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "user data"


def test_force_install_preserves_existing_directory_as_backup(tmp_path: Path) -> None:
    destination = tmp_path / "installed-extension"
    destination.mkdir()
    (destination / "keep.txt").write_text("recoverable", encoding="utf-8")
    (destination / "manifest.json").write_text(
        json.dumps({"name": "Loom — Context Bridge"}),
        encoding="utf-8",
    )

    result = install_extension(
        api_url="https://loom.example.com",
        destination=destination,
        force=True,
    )

    assert result.backup_path is not None
    assert result.backup_path.is_dir()
    assert (result.backup_path / "keep.txt").read_text(encoding="utf-8") == "recoverable"
    assert (destination / "manifest.json").is_file()


def test_force_install_refuses_a_symbolic_link_destination(tmp_path: Path) -> None:
    real_extension = tmp_path / "real-extension"
    real_extension.mkdir()
    (real_extension / "manifest.json").write_text(
        json.dumps({"name": "Loom — Context Bridge"}),
        encoding="utf-8",
    )
    destination = tmp_path / "extension-link"
    destination.symlink_to(real_extension, target_is_directory=True)

    with pytest.raises(ExtensionDistributionError, match="symbolic link"):
        install_extension(
            api_url="https://loom.example.com",
            destination=destination,
            force=True,
        )

    assert destination.is_symlink()
    assert real_extension.is_dir()


def test_package_extension_creates_chrome_ready_credential_free_zip(tmp_path: Path) -> None:
    archive = package_extension(
        api_url="https://loom.example.com",
        output=tmp_path / "loom-extension.zip",
    )

    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        assert "manifest.json" in names
        assert "config.js" in names
        assert "popup.html" in names
        assert all(not name.startswith("loom-extension/") for name in names)
        config = package.read("config.js").decode("utf-8")
        assert 'LOOM_SERVER_URL: "https://loom.example.com"' in config
        assert "DEFAULT_API_KEY: ''" in config


def test_package_extension_refuses_to_overwrite_archive(tmp_path: Path) -> None:
    archive = tmp_path / "loom-extension.zip"
    archive.write_bytes(b"existing")

    with pytest.raises(ExtensionDistributionError, match="already exists"):
        package_extension(api_url="https://loom.example.com", output=archive)

    assert archive.read_bytes() == b"existing"


def test_package_extension_refuses_a_symbolic_link_output(tmp_path: Path) -> None:
    target = tmp_path / "keep.zip"
    target.write_bytes(b"recoverable")
    archive = tmp_path / "loom-extension.zip"
    archive.symlink_to(target)

    with pytest.raises(ExtensionDistributionError, match="symbolic link"):
        package_extension(
            api_url="https://loom.example.com",
            output=archive,
            force=True,
        )

    assert target.read_bytes() == b"recoverable"


def test_package_extension_rejects_an_embedded_project_api_key(tmp_path: Path) -> None:
    source = tmp_path / "extension"
    install_extension(api_url="https://loom.example.com", destination=source)
    leaked_key = "loom_" + "A" * 43
    (source / "leaked.js").write_text(f"const key = '{leaked_key}';\n", encoding="utf-8")

    with pytest.raises(ExtensionDistributionError, match="embedded API credential"):
        package_extension(
            api_url=None,
            source=source,
            output=tmp_path / "loom-extension.zip",
        )


def test_package_extension_rejects_missing_manifest_assets(tmp_path: Path) -> None:
    source = tmp_path / "extension"
    install_extension(api_url="https://loom.example.com", destination=source)
    (source / "shared.js").unlink()

    status = inspect_extension(source)
    assert status.error is not None
    assert "missing assets: shared.js" in status.error

    with pytest.raises(ExtensionDistributionError, match="missing assets: shared.js"):
        package_extension(
            api_url=None,
            source=source,
            output=tmp_path / "loom-extension.zip",
        )


def test_packaged_extension_template_matches_the_development_extension() -> None:
    development = ROOT / "extension"
    packaged = ROOT / "loom" / "browser_extension"
    development_files = {
        path.relative_to(development): path
        for path in development.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }
    packaged_files = {
        path.relative_to(packaged): path
        for path in packaged.rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }

    assert development_files.keys() == packaged_files.keys()
    for relative_path, development_file in development_files.items():
        assert development_file.read_bytes() == packaged_files[relative_path].read_bytes()


def test_extension_cli_has_nested_distribution_commands() -> None:
    parser = build_parser()

    install = parser.parse_args(
        [
            "extension",
            "install",
            "--api-url",
            "https://loom.example.com",
            "--path",
            "/tmp/loom-extension",
            "--force",
        ]
    )
    assert install.extension_command == "install"
    assert install.force is True

    package = parser.parse_args(["extension", "package", "--output", "bundle.zip"])
    assert package.extension_command == "package"
    assert package.output == "bundle.zip"
