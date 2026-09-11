"""Visual-system contracts shared by Loom's public web surfaces."""

from pathlib import Path

from fastapi.testclient import TestClient

from loom.api.main import app

ROOT = Path(__file__).resolve().parents[2]


def test_public_pages_use_the_exaggerated_minimalism_design_system() -> None:
    client = TestClient(app)

    for path, page_class in (
        ("/", "account-page"),
        ("/v1/projects/example/dashboard", "dashboard-page"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "/static/shared/product.css" in response.text
        assert f'class="{page_class}"' in response.text

    stylesheet = (ROOT / "loom/web/shared/product.css").read_text()
    assert "--loom-violet" in stylesheet
    assert "prefers-reduced-motion" in stylesheet
    assert ":focus-visible" in stylesheet


def test_extension_uses_one_packaged_visual_system() -> None:
    source_html = (ROOT / "extension/popup.html").read_text()
    source_css = (ROOT / "extension/popup.css").read_bytes()
    source_js = (ROOT / "extension/popup.js").read_text()
    packaged_css = (ROOT / "loom/browser_extension/popup.css").read_bytes()

    assert "<style>" not in source_html
    assert 'class="popup-page"' in source_html
    assert source_css == packaged_css
    assert b"--loom-violet" in source_css
    assert b"prefers-reduced-motion" in source_css
    assert ".style.display" not in source_js


def test_cli_login_callback_uses_the_product_alert_style() -> None:
    source = (ROOT / "loom/cli/oauth.py").read_text()

    assert 'class="alert" role="status"' in source
    assert "--violet: #8b5cf6" in source
    assert "return to your terminal" in source
