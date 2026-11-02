"""Informe de disponibilidad y SLA.

Fue la funcion de pago mas cara hasta la 1.3.0; ahora esta incluida."""
from datetime import datetime, timedelta, timezone

from app.models import Alert, AlertState, Device
from app.services import sla


def _mk_device(db) -> Device:
    d = Device(name="sla-dev", ip="10.7.0.1")
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_merged_downtime_merges_overlaps():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ivs = [
        (base, base + timedelta(minutes=10)),
        (base + timedelta(minutes=5), base + timedelta(minutes=15)),  # overlaps
        (base + timedelta(minutes=30), base + timedelta(minutes=35)),  # separate
    ]
    # union = [0,15] (15 min) + [30,35] (5 min) = 20 min
    assert sla._merged_downtime_seconds(ivs) == 20 * 60
    assert sla._merged_downtime_seconds([]) == 0.0


def test_el_informe_de_sla_esta_abierto(client, admin_headers):
    """Era la función de pago más cara. Desde la 1.3.0 la tiene todo el mundo."""
    assert client.get("/api/v1/reports/sla?fmt=json", headers=admin_headers).status_code == 200


def test_sla_report_computes_availability(client, admin_headers, db):
    dev = _mk_device(db)
    now = datetime.now(timezone.utc)
    # A 10-minute resolved critical outage inside a 60-minute window.
    db.add(Alert(
        device_id=dev.id, metric="temp_cpu", severity="critical",
        state=AlertState.resolved.value, value=90.0, message="down",
        started_at=now - timedelta(minutes=30), ended_at=now - timedelta(minutes=20),
    ))
    db.commit()

    r = client.get(
        "/api/v1/reports/sla",
        params={
            "fmt": "json",
            "from": (now - timedelta(minutes=60)).isoformat(),
            "to": now.isoformat(),
            "device_ids": str(dev.id),
        },
        headers=admin_headers,
    )
    assert r.status_code == 200
    body = r.json()
    row = next(d for d in body["per_device"] if d["device_id"] == dev.id)
    assert row["incidents"] == 1
    assert 9.5 <= row["downtime_minutes"] <= 10.5
    assert 82.0 <= row["availability_pct"] <= 84.5   # (60-10)/60 ≈ 83.3%
    assert row["mttr_minutes"] is not None
    assert row["sla_met"] is False                    # 83% < 99.9% target


def test_sla_availability_100_without_incidents(client, admin_headers, db):
    dev = _mk_device(db)
    r = client.get("/api/v1/reports/sla", params={"fmt": "json", "device_ids": str(dev.id)},
                   headers=admin_headers)
    row = next(d for d in r.json()["per_device"] if d["device_id"] == dev.id)
    assert row["availability_pct"] == 100.0
    assert row["incidents"] == 0
    assert row["sla_met"] is True


def test_sla_pdf(client, admin_headers):
    r = client.get("/api/v1/reports/sla?fmt=pdf", headers=admin_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
