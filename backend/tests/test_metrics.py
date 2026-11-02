from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.models import Device, MetricPoint


def _seed_points(db, device_id: int, metric_name: str, n: int = 20):
    dev = db.get(Device, device_id)
    metric = next(m for m in dev.metrics if m.name == metric_name)
    base = datetime.now(timezone.utc) - timedelta(minutes=n)
    for i in range(n):
        db.add(MetricPoint(
            time=base + timedelta(minutes=i), device_id=device_id,
            metric_id=metric.id, value=40.0 + i, status=0, latency_ms=5,
        ))
    db.commit()
    return metric.id


def test_query_raw_series(client: TestClient, db, sample_device: dict, operator_headers: dict):
    _seed_points(db, sample_device["id"], "temp_cpu", 10)
    r = client.get(
        f"/api/v1/metrics?device_id={sample_device['id']}&metric=temp_cpu&agg=raw",
        headers=operator_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["aggregation"] == "raw"
    assert len(body["samples"]) == 10
    assert body["unit"]  # temp_cpu has a unit


def test_query_aggregated_series(client: TestClient, db, sample_device: dict, operator_headers: dict):
    _seed_points(db, sample_device["id"], "temp_cpu", 30)
    r = client.get(
        f"/api/v1/metrics?device_id={sample_device['id']}&metric=temp_cpu&agg=5m",
        headers=operator_headers,
    )
    assert r.status_code == 200
    # 30 one-minute points bucket into far fewer 5-minute buckets.
    assert len(r.json()["samples"]) < 30


def test_query_unknown_metric(client: TestClient, sample_device: dict, operator_headers: dict):
    r = client.get(
        f"/api/v1/metrics?device_id={sample_device['id']}&metric=nope",
        headers=operator_headers,
    )
    assert r.status_code == 404


def test_query_bad_aggregation(client: TestClient, sample_device: dict, operator_headers: dict):
    r = client.get(
        f"/api/v1/metrics?device_id={sample_device['id']}&metric=temp_cpu&agg=7x",
        headers=operator_headers,
    )
    assert r.status_code == 400


def test_query_from_after_to(client: TestClient, sample_device: dict, operator_headers: dict):
    frm = "2030-01-02T00:00:00Z"
    to = "2030-01-01T00:00:00Z"
    r = client.get(
        f"/api/v1/metrics?device_id={sample_device['id']}&metric=temp_cpu&from={frm}&to={to}",
        headers=operator_headers,
    )
    assert r.status_code == 400


def test_export_csv(client: TestClient, db, sample_device: dict, operator_headers: dict):
    _seed_points(db, sample_device["id"], "temp_cpu", 5)
    r = client.get(
        f"/api/v1/metrics/export?device_id={sample_device['id']}&metric=temp_cpu&fmt=csv",
        headers=operator_headers,
    )
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "time,value,status,unit" in r.text


def test_export_json(client: TestClient, db, sample_device: dict, operator_headers: dict):
    _seed_points(db, sample_device["id"], "temp_cpu", 5)
    r = client.get(
        f"/api/v1/metrics/export?device_id={sample_device['id']}&metric=temp_cpu&fmt=json",
        headers=operator_headers,
    )
    assert r.status_code == 200
    assert r.json()["metric"] == "temp_cpu"
