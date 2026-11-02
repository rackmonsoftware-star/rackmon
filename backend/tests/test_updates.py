"""Update-check & vendor announcements: opt-in, semver, graceful failure."""
from app.services import updates


def _enable(client, admin_headers, **cfg):
    r = client.put("/api/v1/admin/settings/updates", headers=admin_headers,
                   json={"value": {"enabled": True, **cfg}})
    assert r.status_code == 200, r.text


def test_disabled_by_default_and_never_fetches(client, admin_headers, monkeypatch):
    def boom(url):  # pragma: no cover - must not run
        raise AssertionError("must not fetch the manifest while disabled")

    monkeypatch.setattr(updates, "_fetch", boom)
    updates._reset_cache_for_tests()
    body = client.get("/api/v1/update-status", headers=admin_headers).json()
    assert body["enabled"] is False
    assert body["update_available"] is False
    assert body["current"]  # still echoes the running version


def test_update_available(client, admin_headers, monkeypatch):
    updates._reset_cache_for_tests()
    monkeypatch.setattr(updates, "_fetch", lambda url: {
        "stable": {"version": "999.0.0", "notes": "Huge release", "url": "https://example.invalid/dl"}
    })
    _enable(client, admin_headers)
    body = client.get("/api/v1/update-status", headers=admin_headers).json()
    assert body["enabled"] and body["checked"]
    assert body["latest"] == "999.0.0"
    assert body["update_available"] is True
    assert body["notes"] == "Huge release"
    assert body["download_url"] == "https://example.invalid/dl"


def test_no_update_when_not_newer(client, admin_headers, monkeypatch):
    updates._reset_cache_for_tests()
    monkeypatch.setattr(updates, "_fetch", lambda url: {"stable": {"version": "0.0.1"}})
    _enable(client, admin_headers)
    body = client.get("/api/v1/update-status", headers=admin_headers).json()
    assert body["latest"] == "0.0.1"
    assert body["update_available"] is False


def test_announcement_is_surfaced(client, admin_headers, monkeypatch):
    updates._reset_cache_for_tests()
    monkeypatch.setattr(updates, "_fetch", lambda url: {
        "stable": {"version": "0.0.1"},
        "announcement": {"id": "2026-09", "level": "warning", "title": "Notice", "body": "Read me"},
    })
    _enable(client, admin_headers)
    ann = client.get("/api/v1/update-status", headers=admin_headers).json()["announcement"]
    assert ann and ann["id"] == "2026-09" and ann["level"] == "warning"
    assert ann["title"] == "Notice"


def test_network_failure_is_graceful(client, admin_headers, monkeypatch):
    updates._reset_cache_for_tests()

    def boom(url):
        raise OSError("network down")

    monkeypatch.setattr(updates, "_fetch", boom)
    _enable(client, admin_headers)
    body = client.get("/api/v1/update-status", headers=admin_headers).json()
    assert body["enabled"] is True
    assert body["update_available"] is False
    assert body["latest"] is None  # no crash, just no info


def test_semver_ordering():
    assert updates.is_newer("1.2.0", "1.0.0-mvp")
    assert updates.is_newer("1.0.1", "1.0.0")
    assert not updates.is_newer("1.0.0", "1.0.0")
    assert not updates.is_newer("0.9.9", "1.0.0-mvp")
    assert updates.parse_semver("v2.3") == (2, 3, 0)
    assert updates.parse_semver("1.0.0-mvp") == (1, 0, 0)
