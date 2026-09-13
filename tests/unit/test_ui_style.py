"""Visual-system contracts shared by Loom's public web surfaces."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_public_pages_use_the_exaggerated_minimalism_design_system() -> None:
    frontend = ROOT / "frontend"
    source_files = list((frontend / "src").rglob("*"))

    assert not list((frontend / "src").rglob("*.html"))
    assert not list((frontend / "src").rglob("*.css"))
    assert any(path.name == "page.tsx" for path in source_files)
    assert 'from "@mui/material/Card"' in (frontend / "src/components/account-app.tsx").read_text()
    assert "☰" not in (frontend / "src/components/account-app.tsx").read_text()
    assert "<LoomMark />" in (frontend / "src/components/project-dashboard.tsx").read_text()

    theme = (frontend / "src/theme.ts").read_text()
    assert 'main: "#8b5cf6"' in theme
    assert "prefers-reduced-motion" in theme
    assert "focus-visible" in theme


def test_extension_uses_one_packaged_visual_system() -> None:
    source_html = (ROOT / "extension/popup.html").read_text()
    source_css = (ROOT / "extension/popup.css").read_bytes()
    source_js = (ROOT / "extension/popup.js").read_text()
    packaged_css = (ROOT / "loom/browser_extension/popup.css").read_bytes()
    packaged_logo = (ROOT / "loom/browser_extension/logo.png").read_bytes()

    assert "<style>" not in source_html
    assert 'class="popup-page"' in source_html
    assert 'src="logo.png"' in source_html
    assert source_css == packaged_css
    assert (ROOT / "extension/logo.png").read_bytes() == packaged_logo
    assert b"--loom-violet" in source_css
    assert b"prefers-reduced-motion" in source_css
    assert ".style.display" not in source_js


def test_cli_login_callback_uses_the_product_alert_style() -> None:
    source = (ROOT / "loom/cli/oauth.py").read_text()

    assert 'class="alert" role="status"' in source
    assert "--violet: #8b5cf6" in source
    assert "return to your terminal" in source
