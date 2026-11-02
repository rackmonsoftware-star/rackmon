# Exercising the paths a simulator cannot

The automated suite covers everything that can be made deterministic, which is
almost all of it — the built-in SNMP simulator stands in for hardware. What it
cannot cover is the behaviour of *real* external systems: an SNMP agent that
answers slightly wrong, a directory that refuses a plaintext bind, an identity
provider that redirects a real browser.

This folder is for those. Everything here is run by hand, against something you
stand up locally. None of it is part of CI.

## SNMP v2c against a real agent

`snmp_v2c_test.py` points RackMon's real `SnmpCollector` — not the simulator —
at a `net-snmp` agent and reads the values back.

```bash
# 1. a real SNMP agent on a high port, serving three made-up OIDs
printf 'rocommunity public 127.0.0.1\n\
override 1.3.6.1.4.1.55555.1.1.0 integer 37\n\
override 1.3.6.1.4.1.55555.1.2.0 integer 24\n\
override 1.3.6.1.4.1.55555.1.3.0 integer 4500\n' > /tmp/snmpd.conf
snmpd -f -C -c /tmp/snmpd.conf udp:127.0.0.1:1161 &

# 2. the real collector against it
cd backend && PYTHONPATH=. python scripts/integration/snmp_v2c_test.py
```

Expect 37, 24 and 4500 back. Needs `snmpd` and `snmp` from net-snmp.

**This is the check that earned its keep.** The production collector imported
pysnmp's synchronous API (`from pysnmp.hlapi import getCmd, …`), which was
removed in pysnmp 6.x. Every unit test passed, because they all run against the
simulator; the moment anyone set `RACKMON_POLLER_USE_SIMULATOR=false` against
real hardware, polling raised `RuntimeError: pysnmp is required...` and the
product did nothing at all. It is now on the async API, matching `snmpv3.py`.

## The rest, and what each one needs

These do not have scripts yet. They are written down because they have each
found something, and because the next person to touch that code should know how
to check it rather than guess.

| Path | Stand up | What to look for |
|---|---|---|
| **SNMP v3** | `snmpd` with USM users | Every auth/priv pair you care about. MD5+DES, SHA+AES and SHA-256/512 + AES-192/256 all work. A typo in a protocol name used to silently downgrade the session to cleartext; it now refuses to save. |
| **SNMP traps** | `snmptrap` fired at `run_trap_listener` on udp/1162 | A trap creates an alert, and a storm of them does **not** create a storm of emails. |
| **LDAP** | `glauth`, or a real directory | Bind, search, user-bind; admin group maps to the admin role; a wrong password is rejected. |
| **Active Directory** | A Samba DC | Use `(sAMAccountName={username})`, not the OpenLDAP default. A stock AD **refuses plaintext simple binds**, so LDAPS is not optional in production — plan for it. |
| **OIDC** | Keycloak, or any real IdP | Drive a real browser through authorize → login → callback. The callback redirects into the app and carries the session in the URL fragment, so it never reaches a server log or a `Referer` header. |
| **PostgreSQL / TimescaleDB** | Postgres 16 + the extension | Run the whole suite with `RACKMON_TEST_DATABASE_URL`. Apply `deploy/timescale/20-hypertable.sql` for the hypertable and the 1m/5m/1h continuous aggregates. |
| **Redis, several replicas** | Two instances sharing one Redis | Poll on one, open a WebSocket on the other, and check the readings arrive. That is the whole point of `RACKMON_REDIS_URL`. |
| **Email / webhooks** | `aiosmtpd` and any HTTP sink | That a notification actually leaves the machine. An install with no SMTP host records alerts and never tells anybody — the most common reason RackMon looks like it is working and is not. |

## Things worth knowing, found this way

- **`create_all` does not migrate.** Adding a column to a model left existing
  installs with a stale table and a 500 on any query touching it. There is now
  an additive startup step (`_ensure_columns` in `backend/app/database.py`) that
  adds missing columns; it deliberately never drops or retypes.
- **Latency at scale.** 500 devices and 2500 metrics on PostgreSQL: `/devices`
  0.39 s, `/devices/status` 0.55 s, `/overview` 0.36 s. Sub-second, but that is
  where to look first if a larger fleet feels slow.
- **No SQL injection surface found** by sqlmap at level 3 / risk 2 against the
  search parameters and headers — the queries are parameterised throughout.
- **No memory leak** over ~11,400 requests with the poller running: RSS flat.
- **Auth holds up** against the obvious probes: no token 401, viewer 403,
  tampered JWT 401, `alg:none` forgery 401, privilege escalation 403, lockout
  423.

If you run one of these and it disagrees with what is written here, that is a
bug report worth opening.
