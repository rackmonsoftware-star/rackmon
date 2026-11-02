from app.models import STATUS_CRIT, STATUS_OK, STATUS_WARN, Device, MetricCatalog
from app.services.collector import SimulatedCollector, classify


def _device(device_id: int, tags=None) -> Device:
    d = Device(name=f"d{device_id}", ip="10.0.0.1", tags=tags or [])
    d.id = device_id
    return d


def _metric(metric_id: int, name: str) -> MetricCatalog:
    m = MetricCatalog(device_id=1, name=name, unit="C", oid="1.2.3")
    m.id = metric_id
    m.enabled = True
    return m


def test_classify_temperature_bands():
    assert classify("temp_cpu", 40) == STATUS_OK
    assert classify("temp_cpu", 72) == STATUS_WARN
    assert classify("temp_cpu", 85) == STATUS_CRIT


def test_classify_fan_stall():
    assert classify("fan_rpm", 300) == STATUS_CRIT
    assert classify("fan_rpm", 3000) == STATUS_OK


def test_simulator_returns_reading_per_metric():
    col = SimulatedCollector()
    dev = _device(1)
    metrics = [_metric(1, "temp_cpu"), _metric(2, "temp_inlet"), _metric(3, "fan_rpm")]
    readings = col.poll(dev, metrics)
    assert len(readings) == 3
    names = {r.metric_name for r in readings}
    assert names == {"temp_cpu", "temp_inlet", "fan_rpm"}
    for r in readings:
        assert r.latency_ms >= 0


def test_hot_device_runs_hotter():
    col = SimulatedCollector()
    cool = _device(100, tags=[])
    hot = _device(100, tags=["hot"])  # same id/seed, only the tag differs
    m = [_metric(1, "temp_cpu")]
    cool_temp = col.poll(cool, m)[0].value
    hot_temp = col.poll(hot, m)[0].value
    assert hot_temp > cool_temp


def test_baseline_is_stable_across_calls():
    col = SimulatedCollector()
    dev = _device(7)
    m = [_metric(1, "temp_inlet")]
    # Baselines are seeded from the device id, so repeated polls stay close.
    a = col.poll(dev, m)[0].value
    b = col.poll(dev, m)[0].value
    assert abs(a - b) < 15  # noise + diurnal only, no baseline drift
