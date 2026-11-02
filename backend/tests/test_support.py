"""In-app support forwarding (POST /api/v1/support)."""
from __future__ import annotations

import json
import urllib.error


def test_support_requires_auth(client):
    r = client.post("/api/v1/support", json={"message": "hello"})
    assert r.status_code == 401


def test_support_rejects_empty_message(client, admin_headers):
    r = client.post("/api/v1/support", headers=admin_headers, json={"message": "   "})
    assert r.status_code == 422


def test_support_forwards_to_vendor(client, admin_headers, monkeypatch):
    captured: dict = {}

    class _Resp:
        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr("app.routers.support.urllib.request.urlopen", fake_urlopen)
    r = client.post(
        "/api/v1/support",
        headers=admin_headers,
        json={"message": "the screen is blank", "email": "me@corp.com"},
    )
    assert r.status_code == 202, r.text
    assert r.json() == {"ok": True}
    assert captured["body"]["message"] == "the screen is blank"
    assert captured["body"]["from_email"] == "me@corp.com"
    # instance context is attached so the vendor can triage
    assert captured["body"]["version"]
    assert "edition" in captured["body"]


def test_support_502_when_desk_unreachable(client, admin_headers, monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("app.routers.support.urllib.request.urlopen", boom)
    r = client.post(
        "/api/v1/support", headers=admin_headers, json={"message": "hello there"}
    )
    assert r.status_code == 502


# --- message classification (kind), added in 1.1.0 -------------------------


def _capture(monkeypatch) -> dict:
    """Patch the outbound call and return the dict the payload lands in."""
    captured: dict = {}

    class _Resp:
        def read(self):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr("app.routers.support.urllib.request.urlopen", fake_urlopen)
    return captured


def test_support_forwards_the_kind(client, admin_headers, monkeypatch):
    captured = _capture(monkeypatch)
    r = client.post(
        "/api/v1/support",
        headers=admin_headers,
        json={"message": "sensor reads -40C", "kind": "bug"},
    )
    assert r.status_code == 202, r.text
    assert captured["body"]["kind"] == "bug"


def test_support_kind_defaults_to_question(client, admin_headers, monkeypatch):
    """A 1.0.0 client sends no kind at all; it must still be accepted."""
    captured = _capture(monkeypatch)
    r = client.post("/api/v1/support", headers=admin_headers, json={"message": "how do I add a rack?"})
    assert r.status_code == 202, r.text
    assert captured["body"]["kind"] == "question"


def test_support_rejects_unknown_kind(client, admin_headers):
    r = client.post(
        "/api/v1/support",
        headers=admin_headers,
        json={"message": "hello there", "kind": "complaint"},
    )
    assert r.status_code == 422


# --- support channel availability -----------------------------------------


def test_support_config_reports_enabled(client, admin_headers):
    r = client.get("/api/v1/support/config", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"enabled": True}


def test_support_config_reports_disabled_when_unset(client, admin_headers, monkeypatch):
    """Instances that unset RACKMON_SUPPORT_URL (or run white-label) must be able
    to tell the UI, so it hides a button that could only ever fail."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "support_url", "", raising=False)
    r = client.get("/api/v1/support/config", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_support_503_when_channel_disabled(client, admin_headers, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "support_url", "", raising=False)
    r = client.post("/api/v1/support", headers=admin_headers, json={"message": "hello there"})
    assert r.status_code == 503


def test_support_config_requires_auth(client):
    assert client.get("/api/v1/support/config").status_code == 401
