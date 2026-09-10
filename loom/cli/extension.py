"""Install and package Loom's credential-free Chromium extension bundle."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_BUNDLED_EXTENSION = _PACKAGE_ROOT / "browser_extension"
_MARKER_FILE = ".loom-extension.json"
_SERVER_URL_PATTERN = re.compile(
    r"(?P<prefix>\bLOOM_SERVER_URL\s*:\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)"
)
_DEFAULT_KEY_PATTERN = re.compile(
    r"(?P<prefix>\bDEFAULT_API_KEY\s*:\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)"
)
_GOOGLE_CLIENT_ID_PATTERN = re.compile(
    r"(?P<prefix>\bGOOGLE_OAUTH_CLIENT_ID\s*:\s*)(?P<quote>['\"])(?P<value>.*?)(?P=quote)"
)
_LOOM_API_KEY_PATTERN = re.compile(r"\bloom_[A-Za-z0-9_-]{40,}\b")


class ExtensionDistributionError(ValueError):
    """Raised when an extension install or package operation is unsafe."""


@dataclass(frozen=True)
class ExtensionInstallResult:
    """Result of an extension installation."""

    path: Path
    api_url: str
    google_client_id: str
    backup_path: Path | None = None


@dataclass(frozen=True)
class ExtensionStatus:
    """Local validation result for an installed extension."""

    path: Path
    installed: bool
    manifest_valid: bool
    api_url: str | None
    host_permission: bool
    credentials_embedded: bool
    google_oauth_configured: bool
    error: str | None = None


def default_extension_path() -> Path:
    """Return the user-level extension directory, with a test/CI override."""
    override = os.environ.get("LOOM_EXTENSION_HOME")
    if override:
        return _absolute_path(Path(override))
    return _absolute_path(Path.home() / ".loom" / "extension")


def normalize_api_url(value: str) -> str:
    """Validate and normalize a Loom HTTP API base URL."""
    candidate = value.strip().rstrip("/")
    if not candidate or any(ord(character) < 32 for character in candidate):
        raise ExtensionDistributionError("API URL must be a non-empty HTTP(S) URL.")

    try:
        parsed = urlsplit(candidate)
        # Accessing port validates malformed values such as :not-a-port.
        parsed.port
    except ValueError as exc:
        raise ExtensionDistributionError(f"Invalid API URL: {exc}") from exc

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ExtensionDistributionError("API URL must use http:// or https:// and include a host.")
    if parsed.username is not None or parsed.password is not None:
        raise ExtensionDistributionError("API URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ExtensionDistributionError("API URL must not contain a query string or fragment.")

    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def bundled_api_url() -> str:
    """Read the default server URL from the packaged extension."""
    return _read_api_url(_BUNDLED_EXTENSION / "config.js")


def install_extension(
    *,
    api_url: str,
    destination: Path,
    google_client_id: str,
    force: bool = False,
) -> ExtensionInstallResult:
    """Install a configured extension, preserving recognized prior installs."""
    normalized_url = normalize_api_url(api_url)
    destination = _absolute_path(destination)
    if destination.is_symlink():
        raise ExtensionDistributionError(
            f"Refusing to replace a symbolic link destination: {destination}"
        )
    _validate_bundle(_BUNDLED_EXTENSION)
    destination.parent.mkdir(parents=True, exist_ok=True)

    destination_exists = os.path.lexists(destination)
    if destination_exists and not force:
        raise ExtensionDistributionError(
            f"Extension destination already exists: {destination}. Use --force to replace it."
        )
    if destination_exists and not _is_recognized_extension(destination):
        raise ExtensionDistributionError(
            f"Refusing to replace an unrecognized path: {destination}. Choose another --path."
        )

    staged_path = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    backup_path: Path | None = None
    try:
        _copy_bundle(_BUNDLED_EXTENSION, staged_path)
        _configure_bundle(staged_path, normalized_url, google_client_id)
        _write_marker(staged_path, normalized_url)
        _validate_bundle(staged_path)

        if destination_exists:
            backup_path = _next_backup_path(destination)
            os.replace(destination, backup_path)
        os.replace(staged_path, destination)
    except Exception:
        if backup_path is not None and not os.path.lexists(destination):
            os.replace(backup_path, destination)
            backup_path = None
        raise
    finally:
        if staged_path.exists():
            shutil.rmtree(staged_path)

    return ExtensionInstallResult(
        path=destination,
        api_url=normalized_url,
        google_client_id=google_client_id,
        backup_path=backup_path,
    )


def inspect_extension(path: Path) -> ExtensionStatus:
    """Validate an installed extension without contacting its API."""
    resolved = _absolute_path(path)
    if resolved.is_symlink():
        return ExtensionStatus(
            path=resolved,
            installed=False,
            manifest_valid=False,
            api_url=None,
            host_permission=False,
            credentials_embedded=False,
            google_oauth_configured=False,
            error="Extension path must not be a symbolic link.",
        )
    if not resolved.is_dir():
        return ExtensionStatus(
            path=resolved,
            installed=False,
            manifest_valid=False,
            api_url=None,
            host_permission=False,
            credentials_embedded=False,
            google_oauth_configured=False,
            error="Extension directory does not exist.",
        )

    manifest_valid = False
    api_url: str | None = None
    host_permission = False
    credentials_embedded = False
    google_oauth_configured = False
    errors: list[str] = []

    try:
        manifest = _read_manifest(resolved / "manifest.json")
        manifest_valid = manifest.get("manifest_version") == 3
        if not manifest_valid:
            errors.append("manifest.json is not a Chrome Manifest V3 extension")
    except ExtensionDistributionError as exc:
        manifest = {}
        errors.append(str(exc))

    config_path = resolved / "config.js"
    try:
        config = config_path.read_text(encoding="utf-8")
        api_url = _extract_config_value(config, _SERVER_URL_PATTERN, "LOOM_SERVER_URL")
        api_url = normalize_api_url(api_url)
        default_key = _extract_config_value(config, _DEFAULT_KEY_PATTERN, "DEFAULT_API_KEY")
        google_client_id = _extract_config_value(
            config, _GOOGLE_CLIENT_ID_PATTERN, "GOOGLE_OAUTH_CLIENT_ID"
        )
        google_oauth_configured = (
            google_client_id.endswith(".apps.googleusercontent.com")
            and not google_client_id.startswith("REPLACE_WITH_")
        )
        credentials_embedded = bool(default_key.strip()) or _contains_api_key(resolved)
    except (OSError, UnicodeError, ExtensionDistributionError) as exc:
        errors.append(str(exc))

    try:
        _validate_bundle(resolved)
    except (OSError, UnicodeError, ExtensionDistributionError) as exc:
        validation_error = str(exc)
        if validation_error not in errors:
            errors.append(validation_error)

    if api_url and manifest:
        required_permission = _api_host_permission(api_url)
        permissions = manifest.get("host_permissions", [])
        host_permission = isinstance(permissions, list) and required_permission in permissions
        if not host_permission:
            errors.append(f"manifest.json is missing {required_permission}")
    if credentials_embedded:
        errors.append("config.js contains a default API credential")
    if not google_oauth_configured:
        errors.append("Google OAuth client ID is not configured")

    return ExtensionStatus(
        path=resolved,
        installed=True,
        manifest_valid=manifest_valid,
        api_url=api_url,
        host_permission=host_permission,
        credentials_embedded=credentials_embedded,
        google_oauth_configured=google_oauth_configured,
        error="; ".join(errors) or None,
    )


def package_extension(
    *,
    api_url: str | None,
    output: Path,
    source: Path | None = None,
    google_client_id: str | None = None,
    force: bool = False,
) -> Path:
    """Create a Chrome-ready zip whose manifest sits at the archive root."""
    output = _absolute_path(output)
    if output.suffix.lower() != ".zip":
        output = output.with_suffix(output.suffix + ".zip" if output.suffix else ".zip")
    if output.is_symlink():
        raise ExtensionDistributionError(f"Package output must not be a symbolic link: {output}")
    if os.path.lexists(output) and not force:
        raise ExtensionDistributionError(
            f"Package output already exists: {output}. Use --force to replace it."
        )
    if output.exists() and not output.is_file():
        raise ExtensionDistributionError(f"Package output is not a file: {output}")

    source_path = _absolute_path(source or _BUNDLED_EXTENSION)
    _validate_bundle(source_path)
    selected_url = (
        normalize_api_url(api_url) if api_url else _read_api_url(source_path / "config.js")
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="loom-extension-package-") as temp_dir:
        staged_extension = Path(temp_dir) / "extension"
        staged_extension.mkdir()
        _copy_bundle(source_path, staged_extension)
        selected_google_client_id = google_client_id or _read_google_client_id(
            source_path / "config.js"
        )
        _configure_bundle(staged_extension, selected_url, selected_google_client_id)
        _validate_bundle(staged_extension)

        temporary_archive = Path(temp_dir) / "loom-extension.zip"
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in _bundle_files(staged_extension):
                archive.write(file_path, file_path.relative_to(staged_extension).as_posix())
        os.replace(temporary_archive, output)

    return output


def _configure_bundle(path: Path, api_url: str, google_client_id: str) -> None:
    if (
        not google_client_id.endswith(".apps.googleusercontent.com")
        or google_client_id.startswith("REPLACE_WITH_")
    ):
        raise ExtensionDistributionError("A valid Google extension OAuth client ID is required.")
    config_path = path / "config.js"
    config = config_path.read_text(encoding="utf-8")
    config, server_replacements = _SERVER_URL_PATTERN.subn(
        lambda match: match.group("prefix") + json.dumps(api_url),
        config,
        count=1,
    )
    config, key_replacements = _DEFAULT_KEY_PATTERN.subn(
        lambda match: match.group("prefix") + "''",
        config,
        count=1,
    )
    config, google_replacements = _GOOGLE_CLIENT_ID_PATTERN.subn(
        lambda match: match.group("prefix") + json.dumps(google_client_id),
        config,
        count=1,
    )
    if server_replacements != 1 or key_replacements != 1 or google_replacements != 1:
        raise ExtensionDistributionError("Packaged config.js has an unsupported structure.")
    config_path.write_text(config, encoding="utf-8")

    manifest_path = path / "manifest.json"
    manifest = _read_manifest(manifest_path)
    oauth2 = manifest.get("oauth2")
    if not isinstance(oauth2, dict):
        raise ExtensionDistributionError("manifest.json does not define oauth2.")
    oauth2["client_id"] = google_client_id
    chat_permissions = _content_script_matches(manifest)
    manifest["host_permissions"] = list(
        dict.fromkeys([*chat_permissions, _api_host_permission(api_url)])
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _copy_bundle(source: Path, destination: Path) -> None:
    for source_file in _bundle_files(source):
        relative_path = source_file.relative_to(source)
        destination_file = destination / relative_path
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)


def _bundle_files(path: Path) -> list[Path]:
    files: list[Path] = []
    for candidate in path.rglob("*"):
        if candidate.is_symlink():
            raise ExtensionDistributionError(
                f"Extension bundle must not contain symlinks: {candidate}"
            )
        if candidate.is_file() and candidate.name not in {".DS_Store", _MARKER_FILE}:
            files.append(candidate)
    return sorted(files)


def _validate_bundle(path: Path) -> None:
    if path.is_symlink():
        raise ExtensionDistributionError(f"Extension bundle must not be a symbolic link: {path}")
    if not path.is_dir():
        raise ExtensionDistributionError(f"Extension bundle is missing: {path}")
    required_files = {
        "manifest.json",
        "config.js",
        "background.js",
        "content.js",
        "popup.html",
        "popup.js",
    }
    missing = sorted(name for name in required_files if not (path / name).is_file())
    if missing:
        raise ExtensionDistributionError(
            f"Extension bundle is incomplete; missing: {', '.join(missing)}"
        )
    manifest = _read_manifest(path / "manifest.json")
    missing_assets = sorted(
        asset for asset in _manifest_assets(manifest) if not _safe_asset_path(path, asset).is_file()
    )
    if missing_assets:
        raise ExtensionDistributionError(
            f"Extension manifest references missing assets: {', '.join(missing_assets)}"
        )
    config = (path / "config.js").read_text(encoding="utf-8")
    default_key = _extract_config_value(config, _DEFAULT_KEY_PATTERN, "DEFAULT_API_KEY")
    if default_key.strip() or _contains_api_key(path):
        raise ExtensionDistributionError("Extension bundle contains an embedded API credential.")


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExtensionDistributionError(f"Invalid extension manifest: {path}") from exc
    if not isinstance(parsed, dict):
        raise ExtensionDistributionError(f"Extension manifest must be a JSON object: {path}")
    return parsed


def _content_script_matches(manifest: dict[str, object]) -> list[str]:
    matches: list[str] = []
    content_scripts = manifest.get("content_scripts", [])
    if not isinstance(content_scripts, list):
        raise ExtensionDistributionError("Extension manifest content_scripts must be a list.")
    for script in content_scripts:
        if not isinstance(script, dict):
            continue
        script_matches = script.get("matches", [])
        if isinstance(script_matches, list):
            matches.extend(item for item in script_matches if isinstance(item, str))
    if not matches:
        raise ExtensionDistributionError("Extension manifest has no supported chat origins.")
    return matches


def _manifest_assets(manifest: dict[str, object]) -> set[str]:
    assets: set[str] = set()
    background = manifest.get("background")
    if isinstance(background, dict) and isinstance(background.get("service_worker"), str):
        assets.add(background["service_worker"])
    action = manifest.get("action")
    if isinstance(action, dict) and isinstance(action.get("default_popup"), str):
        assets.add(action["default_popup"])
    icons = manifest.get("icons")
    if isinstance(icons, dict):
        assets.update(value for value in icons.values() if isinstance(value, str))
    content_scripts = manifest.get("content_scripts")
    if isinstance(content_scripts, list):
        for content_script in content_scripts:
            if not isinstance(content_script, dict):
                continue
            for field in ("js", "css"):
                values = content_script.get(field)
                if isinstance(values, list):
                    assets.update(value for value in values if isinstance(value, str))
    return assets


def _safe_asset_path(root: Path, asset: str) -> Path:
    relative = PurePosixPath(asset)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ExtensionDistributionError(f"Unsafe extension asset path in manifest: {asset}")
    return root.joinpath(*relative.parts)


def _read_api_url(config_path: Path) -> str:
    try:
        config = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ExtensionDistributionError(f"Cannot read extension config: {config_path}") from exc
    return normalize_api_url(_extract_config_value(config, _SERVER_URL_PATTERN, "LOOM_SERVER_URL"))


def _read_google_client_id(config_path: Path) -> str:
    try:
        config = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ExtensionDistributionError(f"Cannot read extension config: {config_path}") from exc
    return _extract_config_value(config, _GOOGLE_CLIENT_ID_PATTERN, "GOOGLE_OAUTH_CLIENT_ID")


def _extract_config_value(config: str, pattern: re.Pattern[str], name: str) -> str:
    match = pattern.search(config)
    if not match:
        raise ExtensionDistributionError(f"config.js does not define {name}.")
    return match.group("value")


def _api_host_permission(api_url: str) -> str:
    parsed = urlsplit(api_url)
    return f"{parsed.scheme}://{parsed.netloc}/*"


def _write_marker(path: Path, api_url: str) -> None:
    marker = {
        "managed_by": "loom-cli",
        "api_url": api_url,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    (path / _MARKER_FILE).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def _is_recognized_extension(path: Path) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    marker_path = path / _MARKER_FILE
    if marker_path.is_file():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return isinstance(marker, dict) and marker.get("managed_by") == "loom-cli"
    try:
        manifest = _read_manifest(path / "manifest.json")
    except ExtensionDistributionError:
        return False
    return manifest.get("name") == "Loom — Context Bridge"


def _next_backup_path(destination: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return destination.with_name(f"{destination.name}.backup-{timestamp}-{uuid.uuid4().hex[:8]}")


def _contains_api_key(path: Path) -> bool:
    for file_path in _bundle_files(path):
        if file_path.suffix.lower() not in {".css", ".html", ".js", ".json", ".txt"}:
            continue
        try:
            contents = file_path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        if _LOOM_API_KEY_PATTERN.search(contents):
            return True
    return False


def _absolute_path(path: Path) -> Path:
    """Return an absolute path without following its final symbolic link."""
    return Path(os.path.abspath(path.expanduser()))
