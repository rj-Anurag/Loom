"""Guard the documented public memory-inspection interfaces."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_documents_public_inspection_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for command in ("loom status", "loom links", "loom history"):
        assert command in readme
    for tool in ("list_recent_context", "list_sources"):
        assert tool in readme
    assert "do not create or modify Markdown" in readme
    assert "Dashboard source explorer" in readme
    assert "Observed session" in readme
    assert "intentionally read-only" in readme


def test_docs_site_documents_public_inspection_contracts() -> None:
    docs = (ROOT / "docs/components/docs-site.tsx").read_text(encoding="utf-8")

    for command in ("loom status", "loom links", "loom history"):
        assert command in docs
    for tool in ("list_recent_context", "list_sources"):
        assert tool in docs
    assert "/v1/projects/{project_id}/context/sources" in docs
    assert "Markdown instruction files untouched" in docs
    assert "Dashboard source explorer" in docs
    assert "Structured task results" in docs
    assert "observed session is stored provenance" in docs
