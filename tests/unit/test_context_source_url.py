from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from loom.api.routers.context import WriteContextRequest


def _request(source_url: str) -> WriteContextRequest:
    return WriteContextRequest(
        client_uuid=uuid.uuid4(),
        type="message",
        content="User: source validation",
        version=1,
        source_url=source_url,
    )


@pytest.mark.parametrize(
    "source_url",
    ["javascript:alert(1)", "data:text/html,unsafe", "file:///tmp/private"],
)
def test_context_source_url_rejects_non_http_schemes(source_url: str) -> None:
    with pytest.raises(ValidationError):
        _request(source_url)


@pytest.mark.parametrize(
    "source_url",
    ["https://claude.ai/chat/abc", "http://localhost:8000/conversation/1"],
)
def test_context_source_url_accepts_http_urls(source_url: str) -> None:
    assert str(_request(source_url).source_url) == source_url
