#!/usr/bin/env bash
# Phase 1.12 — Run the concurrent-merge load test.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "=== Loom Load Test: Concurrent Merges ==="
echo ""

# Run with the 'load_test' marker so CI can distinguish these
python -m pytest tests/load/test_concurrent_merges.py -v --tb=short -m load_test \
  -o "markers=load_test: concurrent-merge load test (Phase 1.12)" \
  2>&1

EXIT_CODE=$?

echo ""
if [ -f tests/load/last-report.json ]; then
  echo "=== Report ==="
  python -m json.tool tests/load/last-report.json
fi

exit $EXIT_CODE
