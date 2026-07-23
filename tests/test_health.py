"""Preflight doctor endpoint — pure inspection, must never alter degradation behavior."""
import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app

client = TestClient(app)


@pytest.mark.integration
def test_health_all_dependencies_present(monkeypatch):
    monkeypatch.setattr(app_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(app_module.os.path, "isdir", lambda p: True)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-test")
    report = client.get("/health").json()
    assert report == {"ffmpeg": True, "node": True, "agent_sdk": True, "token": True,
                      "warnings": []}


@pytest.mark.integration
def test_health_all_dependencies_missing(monkeypatch):
    monkeypatch.setattr(app_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(app_module.os.path, "isdir", lambda p: False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    report = client.get("/health").json()
    assert report["ffmpeg"] is False
    assert report["node"] is False
    assert report["agent_sdk"] is False
    assert report["token"] is False
    joined = " ".join(report["warnings"])
    assert "ffmpeg" in joined
    assert "MOCK" in joined


@pytest.mark.integration
def test_health_node_present_but_no_token(monkeypatch):
    monkeypatch.setattr(app_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(app_module.os.path, "isdir", lambda p: True)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    report = client.get("/health").json()
    assert report["ffmpeg"] is True and report["token"] is False
    assert any("CLAUDE_CODE_OAUTH_TOKEN" in w for w in report["warnings"])
