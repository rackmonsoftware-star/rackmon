# RackMon — deployment kit & SNMP temperature reference

Everything you need to **run [RackMon](https://rackmon.app) on your own hardware**, plus a
vendor-by-vendor reference of the **SNMP OIDs that actually return rack temperature**.

RackMon is a self-hosted monitor built around one job: *is anything in my racks getting too hot,
and can I prove it later?* Live per-U thermal heatmaps, SNMP v2c/v3 polling, alerting that
doesn't lie to you, availability/SLA reports and a public status page — in one container.

**[Live demo](https://demo.rackmon.app)** · read-only, real data, no signup — `viewer@rackmon.io` / `viewer12345`

<sub>Heads up on licensing: **RackMon itself is not open source.** This repository holds the
deployment tooling, configuration and reference data, which are MIT-licensed and yours to fork.
The application ships as a container image. The **Community edition is free forever** with
unlimited devices and metrics; a paid Pro tier adds the client-facing features. Details in
[LICENSING.md](LICENSING.md) — no surprises.</sub>

---

## Quickest start

```bash
docker run -d --name rackmon -p 8000:8000 \
  -v rackmon_data:/data \
  -e RACKMON_JWT_SECRET="$(openssl rand -hex 32)" \
  -e RACKMON_MASTER_KEY="$(openssl rand -hex 32)" \
  -e RACKMON_DATABASE_URL="sqlite:////data/rackmon.db" \
  rackmon/rackmon:latest
```

Open <http://localhost:8000>. That's it — SQLite, no external database, nothing to configure.
Point it at real gear when you're ready, or leave the simulator on to look around first.

For anything beyond a single node, use the compose file below.

## What's in here

| Path | What it is |
|---|---|
| [`docker-compose.yml`](docker-compose.yml) | Production single-node stack: RackMon + TimescaleDB + Caddy (TLS) |
| [`docker-compose.sqlite.yml`](docker-compose.sqlite.yml) | Minimal one-container setup, SQLite, no reverse proxy |
| [`.env.example`](.env.example) | Every environment variable, documented, with safe defaults |
| [`snmp-profiles/`](snmp-profiles/) | **The OID reference** — real temperature OIDs per vendor |
| [`alerts/`](alerts/) | Example alerting rules with sane thresholds and hold-down windows |
| [`unraid/`](unraid/) | Unraid Community Applications template |
| [`helm/`](helm/) | Helm chart for Kubernetes |

## The SNMP temperature reference

This is the part worth bookmarking even if you never run RackMon — and if you would rather read
it as a page than as YAML, it lives at
**[rackmon.app/snmp-temperature-oids.html](https://rackmon.app/snmp-temperature-oids.html)**.

Nearly every guide about rack temperature says "poll your vendor's OID" and then doesn't tell you
which one. [`snmp-profiles/`](snmp-profiles/) has them, per vendor, with the two things that
actually trip people up documented alongside: **scaling** (a value of `275` meaning 27.5 °C) and
**units** (a card quietly reporting °F).

Start with the vendor-neutral standard — a surprising amount of modern gear implements it:

```bash
# every sensor value the device exposes (ENTITY-SENSOR-MIB, RFC 3433)
snmpwalk -v2c -c public 10.0.0.10 1.3.6.1.2.1.99.1.1.1.4

# the human-readable names, so you know which index is the inlet
snmpwalk -v2c -c public 10.0.0.10 1.3.6.1.2.1.47.1.1.1.1.2
```

Covered so far: the RFC 3433 standard, Cisco, Juniper, Dell iDRAC, HPE iLO, APC/Schneider NMC.

**Corrections and additions are very welcome** — if you have gear that isn't listed, or an OID
here is wrong on your firmware, please [open an issue](../../issues). Model- and
firmware-specific quirks are exactly the knowledge that's hard to find and easy to share.

## Measure the right thing

The most common mistake is monitoring the CPU temperature the server reports. That tells you how
hot the *chip* is, not how hot the *air reaching it* is — and the second number is the one that
warns you early.

- **Inlet temperature** — cold-aisle air at the front of the rack. This is the metric that matters;
  it's what vendors define their limits against, and it's what moves when cooling fails.
- **Exhaust temperature** — useful as a delta against inlet. A widening gap usually means dirty
  fans, clogged filters, or a box working harder than it should.
- **Internal/CPU** — fine as confirmation, but it lags. By the time it climbs, you're already late.

A sane starting point, measured at the rack inlet: **normal up to 27 °C, warn 28–32 °C, critical
above 32 °C** (ASHRAE class A1–A2 recommends an 18–27 °C inlet range). Check your own vendors'
limits and treat these as a start, not gospel.

## Alerting that stays trustworthy

A thermal alert that cries wolf gets muted within two weeks, and then you have no monitoring at
all — you have noise. Three rules do most of the work, and they're the defaults in
[`alerts/examples.yaml`](alerts/examples.yaml):

- **Hold-down windows** — don't fire on the first poll over threshold. Heat is a slow physical
  quantity; a lone spike is almost always a bad read.
- **Deduplication** — when cooling fails, twenty devices cross the line at once. That's *one*
  incident, not twenty pages.
- **Never fake a recovery** — a missed poll is missing data, **not** a return to normal. Plenty of
  tools mark "recovered" when they've actually gone blind, which is precisely when you need them.

## Links

- **Website:** <https://rackmon.app>
- **Live demo:** <https://demo.rackmon.app>
- **Docs:** <https://rackmon.app/docs.html>
- **How to monitor rack temperature over SNMP:** <https://rackmon.app/guide.html>
- **Guía en español:** <https://rackmon.app/es/monitorizacion-temperatura-racks.html>
- **Compared with Zabbix / PRTG / LibreNMS / Checkmk:** <https://rackmon.app/compare.html>
- **Container image:** <https://hub.docker.com/r/rackmon/rackmon>

## Issues

Bug reports, deployment problems and OID corrections are all welcome here. For anything involving
a licence key or account, email `rackmon.software@gmail.com` instead — please don't post keys in a
public issue.

Found a security issue? See [SECURITY.md](SECURITY.md) — report it privately, not as an issue.
