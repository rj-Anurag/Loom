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
CONDA_ENV="${LOOM_CONDA_ENV:-loom}"

cd "$PROJECT_ROOT"

echo "==> Starting Loom summarization worker (provider: ${SUMMARIZATION_PROVIDER:-stub})"
if [ "${CONDA_DEFAULT_ENV:-}" = "$CONDA_ENV" ]; then
    python -m loom.services.retrieval.summarizer
else
    conda run -n "$CONDA_ENV" python -m loom.services.retrieval.summarizer
fi
