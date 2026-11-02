"""Internal Prometheus metrics for observability (RNF-07)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

POLLS_TOTAL = Counter(
    "rackmon_polls_total", "Total SNMP poll attempts", ["result"]
)
POLL_LATENCY = Histogram(
    "rackmon_poll_latency_seconds",
    "SNMP poll latency in seconds",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
DEVICES_GAUGE = Gauge("rackmon_devices_total", "Configured devices", ["enabled"])
ALERTS_FIRING = Gauge("rackmon_alerts_firing", "Currently firing alerts")
WS_CLIENTS = Gauge("rackmon_ws_clients", "Connected WebSocket clients")
NOTIFICATIONS_TOTAL = Counter(
    "rackmon_notifications_total", "Notifications dispatched", ["channel", "status"]
)
