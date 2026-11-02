# Security policy

## Reporting a vulnerability

Please report security issues privately — either a
[GitHub security advisory](https://github.com/rackmonsoftware-star/rackmon/security/advisories/new)
or **rackmon.software@gmail.com** — rather than opening a public issue. Include what you found,
how to reproduce it, and how you'd like to be credited.

The source is MIT and all of it is in this repository, so you can read the code path you are
reporting on. Past advisories, with what each one actually exposed, are listed at
<https://rackmon.app/security.html#advisories>.

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
- No outbound telemetry, and no licence check of any kind. The optional update check is off
  unless you enable it (`RACKMON_UPDATE_CHECK_ENABLED=false` by default); when on it is a plain
  `GET` of a public JSON file and sends nothing about your install.
- The first administrator is seeded only when the installation has no administrator at all, so
  retiring the factory account does not bring it back on the next restart (fixed in 1.3.0).

## Hardening checklist

- Put management interfaces on a dedicated VLAN; allow only your monitor to reach UDP/161.
- Prefer SNMP v3 with authPriv wherever the hardware supports it.
- Terminate TLS at the reverse proxy (the bundled compose file does this with Caddy).
- Generate `RACKMON_JWT_SECRET` and `RACKMON_MASTER_KEY` with `openssl rand -hex 32` and never
  reuse them between instances.
- Set `RACKMON_ENVIRONMENT=production`. It makes RackMon refuse to start on a factory secret
  instead of warning and carrying on, and it is `development` unless you say otherwise.
- Bind the container's port to `127.0.0.1` and let the reverse proxy be the only thing that
  reaches it from outside.
- Back up the database volume. Your thermal history is the evidence you'll need later.
