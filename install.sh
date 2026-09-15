#!/usr/bin/env bash
set -euo pipefail

readonly DEFAULT_SOURCE="git+https://github.com/rj-Anurag/Loom.git"
INSTALL_SOURCE="${LOOM_INSTALL_SOURCE:-}"
PYTHON_COMMAND="${LOOM_PYTHON:-python3}"

usage() {
  cat <<'EOF'
Install the Loom CLI in an isolated, user-level environment.

Usage: ./install.sh [--source PACKAGE_SOURCE] [--python PYTHON_COMMAND]

When this script is run from a Loom checkout, that checkout is installed by
default. When it is piped from the internet, the public Git repository is used.
LOOM_INSTALL_SOURCE and LOOM_PYTHON provide the same overrides as the flags.
EOF
}

while (($#)); do
  case "$1" in
    --source)
      [[ $# -ge 2 ]] || { echo "Error: --source requires a value." >&2; exit 2; }
      INSTALL_SOURCE="$2"
      shift 2
      ;;
    --python)
      [[ $# -ge 2 ]] || { echo "Error: --python requires a value." >&2; exit 2; }
      PYTHON_COMMAND="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$INSTALL_SOURCE" ]]; then
  SCRIPT_DIRECTORY=""
  if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    SCRIPT_DIRECTORY="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  fi
  if [[ -n "$SCRIPT_DIRECTORY" && -f "$SCRIPT_DIRECTORY/pyproject.toml" \
    && -d "$SCRIPT_DIRECTORY/loom" ]]; then
    INSTALL_SOURCE="$SCRIPT_DIRECTORY"
  else
    INSTALL_SOURCE="$DEFAULT_SOURCE"
  fi
fi

readonly INSTALL_SOURCE
readonly PYTHON_COMMAND

if ! command -v "$PYTHON_COMMAND" >/dev/null 2>&1; then
  echo "Error: Python 3.11 or newer is required." >&2
  exit 1
fi

if ! "$PYTHON_COMMAND" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  echo "Error: Python 3.11 or newer is required." >&2
  exit 1
fi

PIPX_COMMAND=""
PIPX_AS_MODULE=false
if command -v pipx >/dev/null 2>&1; then
  PIPX_COMMAND="$(command -v pipx)"
elif command -v brew >/dev/null 2>&1; then
  echo "Installing pipx with Homebrew..."
  brew install pipx
  PIPX_COMMAND="$(command -v pipx)"
else
  echo "Installing pipx for the current user..."
  "$PYTHON_COMMAND" -m pip install --user pipx
  PIPX_AS_MODULE=true
fi

run_pipx() {
  if [[ "$PIPX_AS_MODULE" == true ]]; then
    "$PYTHON_COMMAND" -m pipx "$@"
  else
    "$PIPX_COMMAND" "$@"
  fi
}

echo "Installing Loom CLI..."
run_pipx install --force "$INSTALL_SOURCE"
run_pipx ensurepath

echo
echo "Loom is installed. Restart your terminal if 'loom' is not yet on PATH."
echo "Verify it with: loom --version"
echo "Install the browser extension with:"
echo "  loom extension install --api-url https://loom-api-zzy0.onrender.com"
echo "Then run 'loom extension path' and load that directory at chrome://extensions."
