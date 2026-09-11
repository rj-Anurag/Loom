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
CONDA_ENV="${LOOM_CONDA_ENV:-loom}"

cd "$PROJECT_ROOT"

echo "==> Starting Loom embedding worker (provider: ${EMBEDDING_PROVIDER:-stub})"
if [ "${CONDA_DEFAULT_ENV:-}" = "$CONDA_ENV" ]; then
    python -m loom.services.retrieval.embedding_worker
else
    conda run -n "$CONDA_ENV" python -m loom.services.retrieval.embedding_worker
fi
