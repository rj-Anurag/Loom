from __future__ import annotations

import pytest

from loom.services.context.provenance import (
    metadata_from_tool_arguments,
    resolve_source_type,
    validate_context_metadata,
)


def test_source_defaults_and_agent_kind_boundaries() -> None:
    assert resolve_source_type("browser", None) == "browser_chat"
    assert resolve_source_type("local", None) == "mcp_agent"
    assert resolve_source_type("local", "codex_cli") == "codex_cli"
    with pytest.raises(ValueError, match="SOURCE_TYPE_DENIED"):
        resolve_source_type("local", "browser_chat")


def test_task_result_metadata_shape() -> None:
    metadata = metadata_from_tool_arguments(
        {
            "task_name": "Implement provenance",
            "files_touched": ["loom/models/context_units.py"],
            "tests": [{"command": "pytest -q", "status": "passed"}],
            "blockers": [],
            "ignored": "not metadata",
        }
    )
    assert metadata == {
        "task_name": "Implement provenance",
        "files_touched": ["loom/models/context_units.py"],
        "tests": [{"command": "pytest -q", "status": "passed"}],
        "blockers": [],
    }


@pytest.mark.parametrize(
    "metadata,error",
    [
        ({"confidence": 2}, "INVALID_METADATA_CONFIDENCE"),
        ({"tests": [{"command": "pytest", "status": "maybe"}]}, "INVALID_METADATA_TESTS"),
        ({"files_touched": "file.py"}, "INVALID_METADATA_FILES_TOUCHED"),
        ({"unknown": True}, "INVALID_METADATA_FIELDS"),
    ],
)
def test_invalid_metadata_is_rejected(metadata, error) -> None:
    with pytest.raises(ValueError, match=error):
        validate_context_metadata(metadata)
