# Security policy

## Reporting a vulnerability

Please report security issues privately to **rackmon.software@gmail.com** rather than opening a
public issue. Include what you found, how to reproduce it, and how you'd like to be credited.

I'm one person, so I won't pretend to a formal SLA. Realistically: acknowledgement within a few
days, and a fix prioritised above everything else.

Please don't test against `demo.rackmon.app` in ways that would degrade it for other people —
run a local instance instead. It takes about ten minutes.

## How RackMon is built

- Secrets (SNMP credentials, LDAP bind passwords) are **encrypted at rest** with a key you supply
  via `RACKMON_MASTER_KEY`; they are never written to logs.
- SNMP v3 supports authPriv. v2c community strings are supported for older gear but are
  unencrypted by design — keep them on an isolated management VLAN.
- Full audit log of authentication and configuration changes.
- Role-based access control; read-only roles genuinely cannot mutate state.
- No outbound telemetry. The optional update check is off unless you enable it
  (`RACKMON_UPDATE_CHECK_ENABLED`).

## Hardening checklist

- Put management interfaces on a dedicated VLAN; allow only your monitor to reach UDP/161.
- Prefer SNMP v3 with authPriv wherever the hardware supports it.
- Terminate TLS at the reverse proxy (the bundled compose file does this with Caddy).
- Generate `RACKMON_JWT_SECRET` and `RACKMON_MASTER_KEY` with `openssl rand -hex 32` and never
  reuse them between instances.
- Back up the database volume. Your thermal history is the evidence you'll need later.
