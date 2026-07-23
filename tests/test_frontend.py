"""Smoke tests for the served single-page UI (no browser — templating/regression guards)."""
import pytest
from fastapi.testclient import TestClient

from app import app
from theme import THEME

client = TestClient(app)


@pytest.mark.integration
def test_index_has_no_cdn_dependency():
    """The page must load fully offline — Tailwind is a vendored static snapshot."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "cdn.tailwindcss.com" not in resp.text
    assert '/static/tailwind.css' in resp.text


@pytest.mark.integration
def test_index_serves_complete_ui():
    """Guards the sentinel-token templating seam: every load-bearing element id must survive,
    and no {{TOKEN}} placeholder may leak into the served page."""
    resp = client.get("/")
    assert resp.status_code == 200
    for element_id in ("dropzone", "fileInput", "filePreviewQueue", "addFileInput",
                       "uploadForm", "doctorBanners", "analyzeBtn", "compileBtn",
                       "reviewSection"):
        assert f'id="{element_id}"' in resp.text, f"missing #{element_id}"
    assert "{{" not in resp.text, "unreplaced template token leaked into the page"
    # Brand chrome comes from whichever theme is active — assert the seam, not one brand's
    # strings, so this test survives any ACTIVE_BRAND/BRAND_CONFIG selection.
    assert f"<title>{THEME.ui_title}</title>" in resp.text
    assert THEME.ui_heading in resp.text


@pytest.mark.integration
def test_vendored_tailwind_is_served():
    resp = client.get("/static/tailwind.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]
    # A class the UI relies on must be present in the snapshot.
    assert ".bg-zinc-950" in resp.text
