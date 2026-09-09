#!/usr/bin/env bash
set -euo pipefail

readonly DEFAULT_SOURCE="git+https://github.com/rj-Anurag/Loom.git"
readonly INSTALL_SOURCE="${LOOM_INSTALL_SOURCE:-$DEFAULT_SOURCE}"
readonly PYTHON_COMMAND="${LOOM_PYTHON:-python3}"

if ! command -v "$PYTHON_COMMAND" >/dev/null 2>&1; then
  echo "Error: Python 3.11 or newer is required." >&2
  exit 1
fi

if ! "$PYTHON_COMMAND" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
  echo "Error: Python 3.11 or newer is required." >&2
  exit 1
fi

PIPX_COMMAND=""
if command -v pipx >/dev/null 2>&1; then
  PIPX_COMMAND="$(command -v pipx)"
elif command -v brew >/dev/null 2>&1; then
  echo "Installing pipx with Homebrew..."
  brew install pipx
  PIPX_COMMAND="$(command -v pipx)"
else
  echo "Installing pipx for the current user..."
  "$PYTHON_COMMAND" -m pip install --user pipx
  PIPX_COMMAND="$($PYTHON_COMMAND -m site --user-base)/bin/pipx"
fi

if [[ ! -x "$PIPX_COMMAND" ]]; then
  echo "Error: pipx was installed but cannot be found at $PIPX_COMMAND." >&2
  exit 1
fi

echo "Installing Loom CLI..."
"$PIPX_COMMAND" install --force "$INSTALL_SOURCE"
"$PIPX_COMMAND" ensurepath

echo
echo "Loom is installed. Restart your terminal if 'loom' is not yet on PATH."
echo "Install the browser extension with:"
echo "  loom extension install --api-url https://loom-api-zzy0.onrender.com"
echo "Then run 'loom extension path' and load that directory at chrome://extensions."
