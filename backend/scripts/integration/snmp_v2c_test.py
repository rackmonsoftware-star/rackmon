"""Point RackMon's REAL pysnmp collector at a live SNMP agent (127.0.0.1:1161)
and verify it reads the exact values the agent serves. This exercises the actual
production SNMP code path — not the built-in simulator."""
import os

os.environ.setdefault("RACKMON_JWT_SECRET", "s")
os.environ.setdefault("RACKMON_MASTER_KEY", "k")

from types import SimpleNamespace

from app.crypto import encrypt
from app.services.collector import SnmpCollector

device = SimpleNamespace(
    ip="127.0.0.1", snmp_port=1161, snmp_version="2c",
    snmp_community_enc=encrypt("public"),
)
metrics = [
    SimpleNamespace(id=1, name="temp_cpu", oid="1.3.6.1.4.1.55555.1.1.0"),
    SimpleNamespace(id=2, name="temp_inlet", oid="1.3.6.1.4.1.55555.1.2.0"),
    SimpleNamespace(id=3, name="fan_rpm", oid="1.3.6.1.4.1.55555.1.3.0"),
]

readings = SnmpCollector(timeout=2.0, retries=1).poll(device, metrics)
for r in readings:
    print(f"  {r.metric_name}: value={r.value} status={r.status} latency={r.latency_ms}ms")

vals = {r.metric_name: r.value for r in readings}
assert vals.get("temp_cpu") == 37.0, f"temp_cpu wrong: {vals}"
assert vals.get("temp_inlet") == 24.0, f"temp_inlet wrong: {vals}"
assert vals.get("fan_rpm") == 4500.0, f"fan_rpm wrong: {vals}"
print("REAL SNMP POLL OK -- RackMon's pysnmp collector read live values from a real SNMP agent")
