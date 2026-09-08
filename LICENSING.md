# Licensing, stated plainly

I'd rather be upfront than have you discover this three files in.

## This repository — MIT

Everything in this repo (compose files, Helm chart, Unraid template, SNMP OID reference,
example alert rules, docs) is MIT-licensed. Fork it, change it, use it with something else
entirely. The OID reference in particular is meant to be useful whether or not you ever run
RackMon.

## RackMon itself — source-available, not open source

The application ships as a container image (`rackmon/rackmon`). **The source is not public.**
If a fully open-source stack is a hard requirement for you, that's a completely reasonable
position and RackMon isn't your tool — [LibreNMS](https://www.librenms.org/) and
[Zabbix](https://www.zabbix.com/) are genuinely good and genuinely open.

## What's free and what isn't

**Community — free forever.** Not a trial, not time-limited, not device-limited:

- Unlimited devices and unlimited metrics
- Per-U rack thermal heatmaps
- SNMP v2c and v3 (authPriv)
- Full metric history and CSV export
- Alerting with hold-down windows, deduplication and escalation
- No account required, no phone-home, no telemetry

**Pro — EUR 390, one-time, per instance.** For running this on behalf of someone else:

- White-label public status page
- Availability / SLA reports as PDF
- RBAC, LDAP/AD, OIDC SSO
- Priority support

The licence is an Ed25519-signed file **verified offline**. There is no licence server to call
home to, and nothing stops working if this project or its author disappears. That was a
deliberate design choice: self-hosted should mean self-hosted.

No subscription. No per-sensor pricing. No "contact sales".
