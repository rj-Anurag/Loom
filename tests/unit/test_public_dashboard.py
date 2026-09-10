"""Public account dashboard route contract."""

from fastapi.testclient import TestClient

from loom.api.main import app


def test_public_dashboard_serves_self_service_onboarding() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Create your Loom account" in response.text
    assert "/v1/auth/signup" in response.text


def test_dashboard_alias_serves_public_account_app() -> None:
    response = TestClient(app).get("/dashboard")

    assert response.status_code == 200
    assert "Your projects" in response.text
