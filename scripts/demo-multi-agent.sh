#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Phase 2.6 — Multi-Agent Concurrent Demo
#
# Runs 3 demo agents (local, cloud, browser) concurrently on a fresh project.
# Requires Loom services to be running (docker compose up -d).
#
# Usage:
#   ./scripts/demo-multi-agent.sh [--api-url http://localhost:8000] [--json]
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Health check ──────────────────────────────────────────────────────────
API_URL="${API_URL:-http://localhost:8000}"

echo "Checking Loom API at $API_URL..."
if ! curl -sf "$API_URL/health" > /dev/null 2>&1; then
    echo "ERROR: Loom API is not reachable at $API_URL."
    echo "       Start services: docker compose up -d"
    exit 1
fi
echo "API is healthy."

# ── Run demo ──────────────────────────────────────────────────────────────
echo ""
echo "Starting Multi-Agent Demo..."
cd "$PROJECT_ROOT"
uv run python -m agents.demo.coordinator "$@"
