"""Anomaly detection: z-score math and the /metrics/anomalies endpoint."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import MetricCatalog, MetricPoint, utcnow
from app.services import anomaly


def test_detect_flags_clear_outlier():
    values = [50.0] * 20
    values[5] = 200.0
    assert anomaly.detect(values, k=3.0) == [5]


def test_detect_flat_and_small_series():
    assert anomaly.detect([50.0] * 20) == []      # zero spread
    assert anomaly.detect([1.0, 200.0, 2.0]) == []  # too few samples


def test_zscores_zero_when_no_spread():
    assert anomaly.zscores([7.0, 7.0, 7.0]) == [0.0, 0.0, 0.0]


def _seed(db, device_id: int) -> None:
    mid = db.scalar(select(MetricCatalog.id).where(
        MetricCatalog.device_id == device_id, MetricCatalog.name == "temp_cpu"))
    now = utcnow()
    for i in range(20):
        db.add(MetricPoint(time=now - timedelta(minutes=i + 1), device_id=device_id,
                           metric_id=mid, value=40.0, status=0, latency_ms=5))
    db.add(MetricPoint(time=now, device_id=device_id, metric_id=mid,
                       value=95.0, status=2, latency_ms=5))  # the spike
    db.commit()


def test_anomalies_endpoint(client, operator_headers, db):
    dev_id = client.post("/api/v1/devices", headers=operator_headers,
                         json={"name": "an-node", "ip": "10.6.6.6"}).json()["id"]
    _seed(db, dev_id)
    r = client.get(f"/api/v1/metrics/anomalies?device_id={dev_id}&metric=temp_cpu",
                   headers=operator_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any(a["value"] == 95.0 for a in body["anomalies"])


def test_anomalies_unknown_metric_404(client, operator_headers):
    dev_id = client.post("/api/v1/devices", headers=operator_headers,
                         json={"name": "n", "ip": "10.6.6.7"}).json()["id"]
    r = client.get(f"/api/v1/metrics/anomalies?device_id={dev_id}&metric=nope",
                   headers=operator_headers)
    assert r.status_code == 404


def test_anomalies_requires_auth(client):
    assert client.get("/api/v1/metrics/anomalies?device_id=1&metric=temp_cpu").status_code == 401
