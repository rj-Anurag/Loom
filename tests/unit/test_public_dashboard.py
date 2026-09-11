"""Public account dashboard route contract."""

from fastapi.testclient import TestClient

from loom.api.main import app


def test_public_dashboard_serves_self_service_onboarding() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Continue to Loom" in response.text
    assert "/v1/auth/google/config" in response.text
    assert "/v1/auth/google/exchange" in response.text
    assert "/v1/auth/signup" not in response.text
    assert "loom init &quot;My Project&quot;" in response.text


def test_dashboard_alias_serves_public_account_app() -> None:
    response = TestClient(app).get("/v1/dashboard")

    assert response.status_code == 200
    assert "Your projects" in response.text
    assert "Project context" in response.text
    assert "/chats" in response.text
    assert 'id="profile-button"' in response.text
    assert "loom_session_token" not in response.text
    assert "/v1/auth/dashboard-session/consume" in response.text
    assert "window.history.replaceState" in response.text
    assert "localStorage" not in response.text
    assert "params.get('session')" not in response.text


def test_legacy_dashboard_alias_serves_public_account_app() -> None:
    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    assert "Your projects" in response.text
