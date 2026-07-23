"""Test runner adapter — executes pytest, ruff, mypy and returns results."""

import subprocess
import sys
from typing import Any

from tools.orchestrator.core import add_node, make_node


def run_tests(state: dict[str, Any], test_path: str | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {}
    commands: list[tuple[str, list[str]]] = [
        ("pytest", [sys.executable, "-m", "pytest", test_path or "tests/", "-v", "--tb=short"]),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("mypy", [sys.executable, "-m", "mypy", "."]),
    ]

    all_passed = True
    for name, cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            passed = result.returncode == 0
            results[name] = {
                "passed": passed,
                "stdout": result.stdout[-500:],
                "stderr": result.stderr[-500:],
            }
            if not passed:
                all_passed = False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            results[name] = {"passed": False, "error": str(e)}
            all_passed = False

    payload: dict[str, Any] = {"all_passed": all_passed, "results": results}
    node = make_node("test", payload)
    add_node(state, node)
    return node
