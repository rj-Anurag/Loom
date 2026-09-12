"""Public account dashboard route contract."""

from fastapi.testclient import TestClient

from loom.api.main import app
from loom.config import settings


def test_public_dashboard_serves_self_service_onboarding() -> None:
    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "http://127.0.0.1:3000/"


def test_dashboard_alias_serves_public_account_app() -> None:
    response = TestClient(app).get("/v1/dashboard", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "http://127.0.0.1:3000/v1/dashboard"


def test_legacy_dashboard_alias_serves_public_account_app() -> None:
    response = TestClient(app).get("/dashboard", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "http://127.0.0.1:3000/dashboard"


def test_project_dashboard_redirects_to_framework_route() -> None:
    response = TestClient(app).get(
        "/v1/projects/example/dashboard",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "http://127.0.0.1:3000/v1/projects/example/dashboard"
    )


def test_managed_frontend_hostname_uses_https(monkeypatch) -> None:
    monkeypatch.setattr(settings, "frontend_host", "loom-frontend.example")

    response = TestClient(app).get("/", follow_redirects=False)

    assert response.headers["location"] == "https://loom-frontend.example/"
