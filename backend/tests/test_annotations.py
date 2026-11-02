"""Timeline annotations: create, list/filter, delete, and permissions."""
from __future__ import annotations


def _device(client, operator_headers) -> int:
    return client.post("/api/v1/devices", headers=operator_headers,
                       json={"name": "ann-dev", "ip": "10.12.12.12"}).json()["id"]


def test_create_and_list(client, operator_headers, viewer_headers):
    dev = _device(client, operator_headers)
    r = client.post("/api/v1/annotations", headers=operator_headers, json={
        "device_id": dev, "metric": "temp_cpu", "text": "replaced fan",
    })
    assert r.status_code == 201
    ann = r.json()
    assert ann["text"] == "replaced fan" and ann["device_id"] == dev

    # Viewer can read.
    listed = client.get(f"/api/v1/annotations?device_id={dev}", headers=viewer_headers).json()
    assert any(a["id"] == ann["id"] for a in listed)
    # Metric filter.
    by_metric = client.get(f"/api/v1/annotations?device_id={dev}&metric=temp_cpu",
                           headers=viewer_headers).json()
    assert len(by_metric) == 1
    assert client.get(f"/api/v1/annotations?device_id={dev}&metric=other",
                      headers=viewer_headers).json() == []


def test_time_range_filter(client, operator_headers):
    dev = _device(client, operator_headers)
    client.post("/api/v1/annotations", headers=operator_headers,
                json={"device_id": dev, "text": "old", "at": "2020-01-01T00:00:00Z"})
    client.post("/api/v1/annotations", headers=operator_headers,
                json={"device_id": dev, "text": "new", "at": "2030-01-01T00:00:00Z"})
    recent = client.get(
        f"/api/v1/annotations?device_id={dev}&from=2025-01-01T00:00:00Z",
        headers=operator_headers).json()
    assert [a["text"] for a in recent] == ["new"]


def test_create_unknown_device_404(client, operator_headers):
    r = client.post("/api/v1/annotations", headers=operator_headers,
                    json={"device_id": 999999, "text": "x"})
    assert r.status_code == 404


def test_delete(client, operator_headers):
    dev = _device(client, operator_headers)
    ann_id = client.post("/api/v1/annotations", headers=operator_headers,
                         json={"device_id": dev, "text": "temp"}).json()["id"]
    assert client.delete(f"/api/v1/annotations/{ann_id}", headers=operator_headers).status_code == 204
    assert client.get(f"/api/v1/annotations?device_id={dev}", headers=operator_headers).json() == []


def test_permissions(client, viewer_headers):
    assert client.post("/api/v1/annotations", json={"device_id": 1, "text": "x"}).status_code == 401
    assert client.post("/api/v1/annotations", headers=viewer_headers,
                       json={"device_id": 1, "text": "x"}).status_code == 403
