#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Run the Loom async embedding worker.
#
# Usage:  scripts/run-embedding-worker.sh
#
# The worker polls the Redis embedding queue, computes embeddings, and
# updates pgvector.  Run one or more instances for concurrent processing.
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

echo "==> Starting Loom embedding worker (provider: ${LOOM_EMBEDDING_PROVIDER:-stub})"
python -m loom.services.retrieval.embedding_worker
