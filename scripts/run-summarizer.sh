#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Run the Loom async summarization worker.
#
# Usage:  scripts/run-summarizer.sh
#
# The worker runs on a timer, grouping unsummarized context units, generating
# LLM summaries, and writing them as summary-type context units with supersedes
# edges.  Run exactly one instance (project-level Redis lock prevents overlap).
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Activate virtual environment (respect LOOM_VENV if set)
VENV="${LOOM_VENV:-$PROJECT_ROOT/.venv}"
if [ -d "$VENV" ]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
fi

cd "$PROJECT_ROOT"

echo "==> Starting Loom summarization worker (provider: ${LOOM_SUMMARIZATION_PROVIDER:-stub})"
python -m loom.services.retrieval.summarizer
