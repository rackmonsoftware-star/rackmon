# SNMP temperature OID reference

The OIDs that actually return temperature, per vendor — with the gotchas that make them wrong.

These are **reference data**, not config files consumed by RackMon. Use them with RackMon,
with Zabbix, with a shell script, with whatever you like.

## Read this before you trust any OID here

Two things break temperature monitoring far more often than a wrong OID:

1. **Scaling.** A device returning `275` may mean **27.5 °C**, not 275 °C. Dell iDRAC does this.
   The ENTITY-SENSOR-MIB tells you explicitly via `entPhySensorScale` and `entPhySensorPrecision`;
   most vendor MIBs expect you to already know.
2. **Units.** Some cards report whatever unit their web UI is configured for. An APC NMC set to
   Fahrenheit will happily hand you `78` and let you believe your rack is on fire.

Always walk the OID on your own hardware, compare against the device's own web interface, and
only then wire it into alerting. **A threshold built on a mis-scaled reading is worse than no
monitoring, because you'll trust it.**

OIDs also move between models and firmware revisions. If one here is wrong for your gear,
please [open an issue](../../issues) — that's exactly the knowledge worth collecting.

## Start with the standard

Before reaching for a vendor MIB, try the vendor-neutral sensor table from RFC 3433. A lot of
modern equipment implements it, and if it answers you get one OID for your whole estate:

```bash
# every sensor value
snmpwalk -v2c -c public 10.0.0.10 1.3.6.1.2.1.99.1.1.1.4
# the names, so you can tell which index is the inlet
snmpwalk -v2c -c public 10.0.0.10 1.3.6.1.2.1.47.1.1.1.1.2
```

On SNMPv3:

```bash
snmpwalk -v3 -l authPriv -u monitor \
  -a SHA -A '<auth-pass>' -x AES -X '<priv-pass>' \
  10.0.0.10 1.3.6.1.2.1.99.1.1.1.4
```

## Coverage

| File | Applies to |
|---|---|
| [`standard-entity-sensor.yaml`](standard-entity-sensor.yaml) | Anything implementing RFC 3433 — **try this first** |
| [`cisco.yaml`](cisco.yaml) | Cisco IOS / IOS-XE / NX-OS |
| [`juniper.yaml`](juniper.yaml) | Junos |
| [`dell-idrac.yaml`](dell-idrac.yaml) | Dell PowerEdge via iDRAC |
| [`hpe-ilo.yaml`](hpe-ilo.yaml) | HPE ProLiant via iLO |
| [`apc-nmc.yaml`](apc-nmc.yaml) | APC / Schneider Network Management Card + probes |

Missing your vendor? Issues and PRs welcome.
