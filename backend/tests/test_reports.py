"""Reporting: SLA/time-over-threshold math and PDF/JSON output."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import MetricCatalog, MetricPoint, utcnow
from app.services import reports


def _seed_points(db, device_id: int) -> None:
    """10 temp_cpu points: 6 ok, 3 warn, 1 crit (max 88.0)."""
    mid = db.scalar(
        select(MetricCatalog.id).where(
            MetricCatalog.device_id == device_id, MetricCatalog.name == "temp_cpu"
        )
    )
    assert mid is not None
    now = utcnow()
    plan = [(0, 40.0)] * 6 + [(1, 70.0)] * 3 + [(2, 88.0)]
    for i, (status, value) in enumerate(plan):
        db.add(MetricPoint(
            time=now - timedelta(minutes=i), device_id=device_id,
            metric_id=mid, value=value, status=status, latency_ms=5,
        ))
    db.commit()


def _make_device(client, headers) -> int:
    return client.post(
        "/api/v1/devices", headers=headers,
        json={"name": "rep-node", "ip": "10.7.7.7", "tags": ["compute"]},
    ).json()["id"]


def test_compute_report_sla_and_hottest(client, operator_headers, db):
    dev_id = _make_device(client, operator_headers)
    _seed_points(db, dev_id)

    end = utcnow() + timedelta(minutes=1)
    start = end - timedelta(days=1)
    rep = reports.compute_report(db, start, end, [dev_id])

    row = next(d for d in rep["per_device"] if d["device_id"] == dev_id)
    assert row["samples"] == 10
    assert row["max_temp"] == 88.0
    # 4 of 10 points are >= warning (3 warn + 1 crit); 1 is critical.
    assert row["pct_over_warn"] == 40.0
    assert row["pct_over_crit"] == 10.0
    assert 0 < row["availability_pct"] <= 100
    assert rep["hottest"][0]["device_id"] == dev_id


def test_adhoc_report_pdf(client, admin_headers, operator_headers, db):
    dev_id = _make_device(client, operator_headers)
    _seed_points(db, dev_id)
    r = client.get("/api/v1/reports/adhoc?fmt=pdf", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_adhoc_report_json(client, admin_headers):
    r = client.get("/api/v1/reports/adhoc?fmt=json", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "alerts_by_severity" in body and "hottest" in body and "per_device" in body


def test_reports_require_auth(client):
    assert client.get("/api/v1/reports/adhoc?fmt=json").status_code == 401
