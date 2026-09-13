"""Public account dashboard route contract."""

from pathlib import Path

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
    assert response.headers["location"] == ("http://127.0.0.1:3000/v1/projects/example/dashboard")


def test_managed_frontend_hostname_uses_https(monkeypatch) -> None:
    monkeypatch.setattr(settings, "frontend_host", "loom-frontend.example")

    response = TestClient(app).get("/", follow_redirects=False)

    assert response.headers["location"] == "https://loom-frontend.example/"


def test_dashboard_reuses_google_sdk_across_logout() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "frontend/src/components/account-app.tsx"
    ).read_text()

    assert 'from "next/script"' in source
    assert 'id="google-identity-services"' in source
    assert source.count("window.google.accounts.id.initialize(") == 1
    assert 'let initializedGoogleClientId = ""' in source
    assert "use_fedcm_for_button: true" in source
    assert 'className="g_id_signout"' in source
    assert "disableAutoSelect()" in source
    assert "setUser(null)" in source
    assert "window.location.reload()" not in source
