from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Alert, AlertRule, AlertState, Device
from app.services.alert_engine import AlertEngine, evaluate_condition
from app.services.collector import Reading


def _reading(value: float, name: str = "temp_cpu") -> Reading:
    return Reading(metric_id=1, metric_name=name, value=value, status=0, latency_ms=5)


def _make_device(db, tags=None, maintenance=False) -> Device:
    dev = Device(name="dev", ip="10.0.0.2", tags=tags or [])
    if maintenance:
        dev.maintenance_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db.add(dev)
    db.commit()
    db.refresh(dev)
    return dev


def _make_rule(db, **over) -> AlertRule:
    base = dict(name="r", scope_type="global", metric="temp_cpu", operator=">",
                threshold=70.0, for_seconds=0, severity="critical", throttle_seconds=0,
                enabled=True)
    base.update(over)
    rule = AlertRule(**base)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _active(db, device_id):
    return db.scalars(
        select(Alert).where(Alert.device_id == device_id, Alert.state != AlertState.resolved.value)
    ).all()


def test_evaluate_condition_operators():
    assert evaluate_condition(">", 80, 70) is True
    assert evaluate_condition("<", 60, 70) is True
    assert evaluate_condition(">=", 70, 70) is True
    assert evaluate_condition("<=", 70, 70) is True
    assert evaluate_condition("==", 70, 70) is True
    assert evaluate_condition("!=", 71, 70) is True
    assert evaluate_condition(">", 60, 70) is False


def test_fires_immediately_when_for_zero(db):
    dev = _make_device(db)
    _make_rule(db, for_seconds=0)
    eng = AlertEngine()
    changed = eng.process(db, dev, [_reading(85)])
    db.commit()
    assert len(changed) == 1
    active = _active(db, dev.id)
    assert len(active) == 1
    assert active[0].state == AlertState.firing.value
    assert active[0].severity == "critical"


def test_persistence_window_delays_firing(db):
    dev = _make_device(db)
    _make_rule(db, for_seconds=300)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(85)])  # first crossing, held ~0s
    db.commit()
    assert _active(db, dev.id) == []  # not yet, within the 300s window


def test_deduplicates_active_alert(db):
    dev = _make_device(db)
    _make_rule(db, for_seconds=0)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(85)])
    db.commit()
    eng.process(db, dev, [_reading(90)])  # still over threshold
    db.commit()
    assert len(_active(db, dev.id)) == 1  # no second alert


def test_auto_resolves_after_clear_cycles(db):
    dev = _make_device(db)
    _make_rule(db, for_seconds=0)
    eng = AlertEngine()  # resolve_cycles defaults to 2
    eng.process(db, dev, [_reading(85)])
    db.commit()
    assert len(_active(db, dev.id)) == 1

    eng.process(db, dev, [_reading(40)])  # clear #1
    db.commit()
    assert len(_active(db, dev.id)) == 1  # needs two clears

    eng.process(db, dev, [_reading(40)])  # clear #2
    db.commit()
    assert _active(db, dev.id) == []
    resolved = db.scalars(
        select(Alert).where(Alert.device_id == dev.id, Alert.state == AlertState.resolved.value)
    ).all()
    assert len(resolved) == 1
    assert resolved[0].ended_at is not None


def test_maintenance_suppresses_firing(db):
    dev = _make_device(db, maintenance=True)
    _make_rule(db, for_seconds=0)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(95)])
    db.commit()
    assert _active(db, dev.id) == []


def test_tag_scope_matches_only_tagged_devices(db):
    tagged = _make_device(db, tags=["compute"])
    untagged = _make_device(db, tags=["network"])
    _make_rule(db, scope_type="tag", scope_ref="compute", for_seconds=0)
    eng = AlertEngine()
    eng.process(db, tagged, [_reading(85)])
    eng.process(db, untagged, [_reading(85)])
    db.commit()
    assert len(_active(db, tagged.id)) == 1
    assert _active(db, untagged.id) == []


def test_nan_reading_does_not_fire(db):
    dev = _make_device(db)
    _make_rule(db, for_seconds=0)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(float("nan"))])
    db.commit()
    assert _active(db, dev.id) == []


def test_nan_reading_does_not_resolve_active_alert(db):
    """A missing reading is 'unknown', not 'recovered'. It must never resolve a
    live alert — otherwise a transient poll gap sends a false all-clear."""
    dev = _make_device(db)
    _make_rule(db, for_seconds=0)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(85)])  # fire
    db.commit()
    assert len(_active(db, dev.id)) == 1

    eng.process(db, dev, [_reading(float("nan"))])  # gap #1
    eng.process(db, dev, [_reading(float("nan"))])  # gap #2
    db.commit()
    assert len(_active(db, dev.id)) == 1  # still firing, not resolved


def test_maintenance_does_not_resolve_active_alert(db):
    """Maintenance suppresses; it must not resolve an already-firing alert."""
    dev = _make_device(db)
    _make_rule(db, for_seconds=0)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(85)])  # fire (not in maintenance)
    db.commit()
    assert len(_active(db, dev.id)) == 1

    dev.maintenance_until = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    eng.process(db, dev, [_reading(40)])  # would be "clear" but we're in maintenance
    eng.process(db, dev, [_reading(40)])
    db.commit()
    assert len(_active(db, dev.id)) == 1  # suppressed, not resolved


def test_auto_resolve_sets_resolved_at(db):
    dev = _make_device(db)
    _make_rule(db, for_seconds=0)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(85)])
    eng.process(db, dev, [_reading(40)])
    eng.process(db, dev, [_reading(40)])
    db.commit()
    resolved = db.scalars(
        select(Alert).where(Alert.device_id == dev.id, Alert.state == AlertState.resolved.value)
    ).all()
    assert len(resolved) == 1
    assert resolved[0].resolved_at is not None
    assert resolved[0].ended_at is not None


def test_acked_alert_is_not_renotified(db, monkeypatch):
    calls: list = []
    monkeypatch.setattr("app.services.notifier.dispatch", lambda *a, **k: calls.append(a))
    dev = _make_device(db)
    _make_rule(db, for_seconds=0, throttle_seconds=1)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(85)])  # fire -> 1 dispatch
    db.commit()
    assert len(calls) == 1

    alert = _active(db, dev.id)[0]
    alert.state = AlertState.acked.value
    db.commit()
    key = next(iter(eng._pending))
    eng._pending[key].last_notified_at = datetime.now(timezone.utc) - timedelta(hours=1)
    calls.clear()

    eng.process(db, dev, [_reading(90)])  # still over, throttle elapsed
    db.commit()
    assert calls == []  # a human owns it -> no re-notification spam


def test_snoozed_alert_is_not_renotified(db, monkeypatch):
    calls: list = []
    monkeypatch.setattr("app.services.notifier.dispatch", lambda *a, **k: calls.append(a))
    dev = _make_device(db)
    _make_rule(db, for_seconds=0, throttle_seconds=1)
    eng = AlertEngine()
    eng.process(db, dev, [_reading(85)])
    db.commit()

    alert = _active(db, dev.id)[0]
    alert.snoozed_until = datetime.now(timezone.utc) + timedelta(minutes=30)
    db.commit()
    key = next(iter(eng._pending))
    eng._pending[key].last_notified_at = datetime.now(timezone.utc) - timedelta(hours=1)
    calls.clear()

    eng.process(db, dev, [_reading(90)])
    db.commit()
    assert calls == []  # snoozed -> stay silent until it expires
