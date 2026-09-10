from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from loom.services.context.service import (
    _decode_history_cursor,
    _encode_history_cursor,
)


def test_history_cursor_round_trip() -> None:
    created_at = datetime(2026, 9, 7, 12, 30, 45, 123456, tzinfo=UTC)
    unit_id = uuid.uuid4()

    cursor = _encode_history_cursor(created_at, unit_id)

    assert _decode_history_cursor(cursor) == (created_at, unit_id)


@pytest.mark.parametrize("cursor", ["", "not-a-cursor", "bm8tdGltZXN0YW1wfG5vdC1hLXV1aWQ"])
def test_history_cursor_rejects_invalid_values(cursor: str) -> None:
    with pytest.raises(ValueError, match="INVALID_CURSOR"):
        _decode_history_cursor(cursor)
