"""Unit contracts for credential parsing and browser-origin policy."""

import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from loom.api.auth import (
    AuthContext,
    _extract_bearer_token,
    _validate_cookie_request,
    require_project_agent,
    require_project_agent_scope,
)
from loom.api.main import validate_security_config
from loom.config import Settings, settings


@pytest.mark.parametrize(
    "header",
    [
        None,
        "Basic abc",
        "Bearer",
        "Bearer ",
        "Bearer token with spaces",
        f"Bearer {'x' * 513}",
    ],
)
def test_malformed_authorization_headers_receive_a_generic_challenge(
    header: str | None,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _extract_bearer_token(header)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


def test_bearer_scheme_is_case_insensitive() -> None:
    assert _extract_bearer_token("bearer opaque-token") == "opaque-token"


def test_cookie_credentials_receive_the_same_input_bounds() -> None:
    with pytest.raises(HTTPException):
        _extract_bearer_token(None, f"loom_session_{'x' * 513}")


def test_configured_browser_origins_are_normalized() -> None:
    configured = Settings(
        _env_file=None,
        cors_allowed_origins="https://one.example/, https://two.example",
    )

    assert configured.browser_origins == (
        "https://one.example",
        "https://two.example",
    )


def test_cookie_mutations_reject_an_untrusted_origin() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/auth/logout",
            "headers": [(b"origin", b"https://attacker.example")],
        }
    )

    with pytest.raises(HTTPException, match="UNTRUSTED_ORIGIN") as exc_info:
        _validate_cookie_request(request, authorization=None)

    assert exc_info.value.status_code == 403


async def test_project_agent_dependencies_apply_explicit_scope_policy() -> None:
    authorized_project = uuid.uuid4()
    another_project = uuid.uuid4()
    auth = AuthContext(agent_id=uuid.uuid4(), project_id=authorized_project)

    assert await require_project_agent(authorized_project, auth) == auth
    with pytest.raises(HTTPException) as hidden_error:
        await require_project_agent(another_project, auth)
    assert hidden_error.value.status_code == 404

    with pytest.raises(HTTPException) as scope_error:
        await require_project_agent_scope(another_project, auth)
    assert scope_error.value.status_code == 403
    assert scope_error.value.detail == "AGENT_MISMATCH"


def test_production_requires_https_browser_origins(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "frontend_host", "")
    monkeypatch.setattr(settings, "frontend_url", "http://loom.example")
    monkeypatch.setattr(settings, "cors_allowed_origins", "")
    monkeypatch.setattr(settings, "allow_legacy_uuid_tokens", False)

    with pytest.raises(RuntimeError, match="must use HTTPS"):
        validate_security_config()


def test_production_rejects_legacy_uuid_credentials(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "frontend_host", "loom.example")
    monkeypatch.setattr(settings, "cors_allowed_origins", "")
    monkeypatch.setattr(settings, "allow_legacy_uuid_tokens", True)

    with pytest.raises(RuntimeError, match="Legacy UUID credentials"):
        validate_security_config()
