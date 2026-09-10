"""Security policy for first-run project bootstrapping."""

import pytest
from fastapi import HTTPException

from loom.api.routers.extension import validate_bootstrap_request
from loom.config import settings


def test_development_allows_unconfigured_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "bootstrap_token", "")

    validate_bootstrap_request(None)


def test_production_requires_configured_bootstrap_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "bootstrap_token", "")

    with pytest.raises(HTTPException) as exc_info:
        validate_bootstrap_request(None)

    assert exc_info.value.status_code == 503


def test_configured_bootstrap_token_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "bootstrap_token", "operator-secret")

    with pytest.raises(HTTPException) as exc_info:
        validate_bootstrap_request("wrong")

    assert exc_info.value.status_code == 401
    validate_bootstrap_request("operator-secret")
