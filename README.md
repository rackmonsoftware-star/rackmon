# RackMon

**Self-hosted rack temperature monitoring over SNMP.** Poll every server, switch,
UPS and PDU you already own, watch one live heat-map of the whole room, and get
told before anything cooks.

[![Live demo](https://img.shields.io/badge/live%20demo-no%20signup-06b6d4?style=flat-square)](https://demo.rackmon.app)
[![Docker](https://img.shields.io/badge/docker-rackmon%2Frackmon-2496ed?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/r/rackmon/rackmon)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

<p align="center">
  <img src="https://rackmon.app/assets/overview-dark.png" alt="RackMon overview: a live per-U thermal map of six racks" width="900">
</p>

**[Try it right now at demo.rackmon.app](https://demo.rackmon.app)** — read-only, no
sign-up, 109 real devices across six racks.

```bash
docker run -d --name rackmon -p 8000:8000 \
  -e RACKMON_JWT_SECRET="$(openssl rand -hex 32)" \
  -e RACKMON_MASTER_KEY="$(openssl rand -hex 32)" \
  -e RACKMON_DATABASE_URL="sqlite:////app/data/rackmon.db" \
  -v rackmon-data:/app/data \
  rackmon/rackmon:latest
```

Then open **http://localhost:8000**. It boots with a built-in SNMP simulator, so
the dashboard has something in it before you have wired up a single device.

---

## Why another monitoring tool

Zabbix, LibreNMS and Checkmk can all read a temperature OID. What they do not do
is make rack thermals the thing you see first, and getting there is a weekend of
templates. RackMon does one job: **the temperature of the air going into your
equipment**, which is the number every published limit — ASHRAE's included — is
written against. One container, about ten minutes, and the colour on the screen
agrees with the alert that fires.

It is **not** trying to replace your observability stack. No application metrics,
no logs, no network topology. If you need those, keep Zabbix and run this
alongside it. [Honest comparison, including where it loses.](https://rackmon.app/compare.html)

---

## Status

Stable and in use. Current release **1.3.0**.

Everything is included: SSO, LDAP/Active Directory, SLA reports, the public
status page and white-label branding. There is no Pro edition, no licence key and
no device limit — RackMon used to be open-core and that is over.

- **522 backend tests** across 67 files, **49 frontend tests**, and an
  **API&harr;frontend contract test** that pins every field the UI reads, so a
  serialization drift cannot silently break a screen.
- Runs with **zero external hardware** thanks to a built-in SNMP simulator —
  including the whole test suite.
- The changelog is not a feature list: it says plainly what was broken and who it
  hurt. Recent releases closed a device that died without raising any alert, an
  SLA report that gave a dead machine 100% availability, and an SNMPv3 session
  that could silently downgrade to cleartext.
  [Read it.](https://rackmon.app/changelog.html)

## Highlights

- **Live rack thermal map** — every device coloured by temperature on a
  cyan→green→amber→red ramp, so a single glance tells you where the heat is.
- **Real-time telemetry** over WebSockets: metric cards and sparklines update as
  the poller reads each device; no manual refresh.
- **Alerting engine** with persistence windows (`for N seconds`), de-duplication,
  severity levels, throttled re-notification, auto-resolve, and maintenance
  suppression. Rules can be scoped globally, by tag, or to a single device.
- **History & export** — per-metric charts over 1h/6h/24h/7d with raw/1m/5m/1h
  aggregation, plus CSV/JSON export.
- **RBAC** (viewer / operator / admin), Argon2id password hashing, optional TOTP
  MFA, login lockout, refresh tokens, and a full **audit log**.
- **Ops-ready**: `/health` probe, Prometheus metrics at `/metrics`, structured
  JSON logs, security headers, retention sweeps.
- **Polished dark "NOC" UI** — React + TypeScript, hand-rendered SVG charts (no
  charting dependency), English/Spanish i18n, light/dark themes.

---

## Architecture

```
                 ┌──────────────┐   WebSocket + REST
   Browser ──────▶   Caddy      ├──────────────┐
   (SPA)          │  (edge/TLS) │              │
                 └──────────────┘              ▼
                                       ┌──────────────────┐
                                       │  FastAPI (api)   │
                                       │  ┌────────────┐  │
                                       │  │  Poller    │  │  SNMP (or simulator)
                                       │  │  Alert eng.│  │──────────────▶ Devices
                                       │  │  Scheduler │  │
                                       │  └────────────┘  │
                                       │  Realtime hub    │  (in-proc pub/sub;
                                       └────────┬─────────┘   Redis for scale-out)
                                                │
                                                ▼
                                       ┌──────────────────┐
                                       │  TimescaleDB /   │
                                       │  PostgreSQL      │
                                       └──────────────────┘
```

The API process serves the built SPA and the JSON/WebSocket API from one origin.
A background **poller** reads each device on its own interval, writes points to
the time-series table, updates a latest-value cache, and feeds the **alert
engine**; results fan out to connected browsers through an in-process realtime
hub. For horizontal scale the same hub interface is backed by Redis (provisioned
in compose, not required for single-node).

**Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · PyJWT · Argon2 · pysnmp ·
Prometheus client · React 18 · TypeScript · Vite · Tailwind CSS.

---

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env: set DB_PASSWORD, RACKMON_JWT_SECRET, RACKMON_MASTER_KEY,
#            RACKMON_ADMIN_EMAIL, RACKMON_ADMIN_PASSWORD
#   (generate secrets with:  openssl rand -hex 32)
# Compose refuses to start if any of them is missing, and says which.

docker compose up --build
```

Open **http://localhost:8080** and sign in with the admin email and password you
set in `.env` — this stack runs with `RACKMON_ENVIRONMENT=production`, so there
is no default account and RackMon refuses to start on a factory secret. The
stack is Caddy (edge), the API (serving the SPA and running the poller
in-process), and TimescaleDB. Demo data (7 devices across two racks + example
rules) is seeded on first boot so the dashboard isn't empty.

*(Optional)* turn on Timescale hypertables + continuous aggregates once, after the
first boot:

```bash
docker compose exec -T db psql -U rackmon -d rackmon < deploy/timescale/20-hypertable.sql
```

---

## Local development

Two terminals. **Backend:**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export RACKMON_JWT_SECRET=dev-secret
export RACKMON_MASTER_KEY=dev-master-key
uvicorn app.main:app --reload          # API on http://localhost:8000
```

The backend defaults to a local SQLite file (`rackmon.db`) and seeds demo data,
so it's fully functional on its own. Interactive API docs: **http://localhost:8000/docs**.

**Frontend** (hot-reloading dev server, proxies the API to `:8000`):

```bash
cd frontend
npm install
npm run dev                            # UI on http://localhost:5173
```

To serve the SPA from the backend (as in production), build it — Vite emits into
`backend/app/static`, which FastAPI serves automatically:

```bash
cd frontend && npm run build
# now http://localhost:8000 serves the full app
```

---

## Default credentials

| Role     | Email                 | Password                                    |
|----------|-----------------------|---------------------------------------------|
| Admin    | `admin@rackmon.io`    | `admin12345` — development default          |
| Viewer   | `viewer@rackmon.io`   | only created if you set `RACKMON_VIEWER_PASSWORD` |

The admin default is for running locally with zero configuration. Set
`RACKMON_ADMIN_EMAIL` / `RACKMON_ADMIN_PASSWORD` for any real deployment — with
`RACKMON_ENVIRONMENT=production` RackMon refuses to start while the default is
still in use.

That account is seeded **only when the installation has no administrator at
all**. So once you have replaced it — renamed it to your own address, or created
your own and deleted it — it stays gone. Until 1.3.0 the check was "is this exact
email missing?", which meant both of those routes handed the next restart a
brand-new admin carrying the default password, silently.

The read-only account is **not** seeded with a factory password. It used to be,
and that password was printed on rackmon.app, which made it a published
credential on every install that followed the quickstart. Set
`RACKMON_VIEWER_PASSWORD` if you want the account; otherwise create read-only
users from Admin → Users. An install upgrading from an older version has that
account disabled automatically **if** its password is still the published one —
if you had changed it, it is left untouched.

---

## Configuration

All settings are environment variables prefixed `RACKMON_` (or an `.env` file).
The most useful:

| Variable                       | Default                     | Purpose                                             |
|--------------------------------|-----------------------------|-----------------------------------------------------|
| `RACKMON_DATABASE_URL`         | `sqlite:///./rackmon.db`    | Any SQLAlchemy URL (Postgres/Timescale in prod).    |
| `RACKMON_JWT_SECRET`           | *(dev placeholder)*         | **Set in prod.** Signs auth tokens.                 |
| `RACKMON_MASTER_KEY`           | *(dev placeholder)*         | **Set in prod.** Encrypts SNMP creds at rest.       |
| `RACKMON_POLLER_ENABLED`       | `true`                      | Run the background poller in this process.          |
| `RACKMON_POLLER_USE_SIMULATOR` | `true`                      | `false` → poll real devices over SNMP.              |
| `RACKMON_POLLER_TICK_SECONDS`  | `3.0`                       | How often the poll loop wakes.                      |
| `RACKMON_SEED_DEMO_DATA`       | `true`                      | Seed demo devices/rules on startup.                 |
| `RACKMON_RAW_RETENTION_DAYS`   | `30`                        | Raw points older than this are pruned.              |
| `RACKMON_CORS_ORIGINS`         | localhost dev origins       | JSON list of allowed browser origins.               |
| `RACKMON_SMTP_HOST` …          | *(unset)*                   | Optional SMTP for email notifications.              |

Every setting, with its real default and a comment, is in [`.env.example`](.env.example);
`backend/app/config.py` is the file they are read from.

---

## Testing

```bash
cd backend
python -m pytest -q         # 522 tests
python -m pytest --cov=app  # with coverage
```

The suite covers auth/RBAC, crypto, device & metric APIs, the alert engine's
state machine, rule validation, the realtime hub, WebSocket auth, and full
poller→alert integration. The simulator is seeded per-test for determinism.

### Frontend unit tests

```bash
cd frontend
npm test            # Vitest (component + logic tests)
npm run test:cov    # with coverage
```

### End-to-end (real browser, with screenshots)

A Playwright suite drives a real Chromium through the whole app — logs in, walks
every page, opens a device, runs a discovery scan, compares metrics — and saves
screenshots. Run it against a running instance:

```bash
# 1. Start RackMon (e.g. docker compose up  ->  http://localhost:8080)
cd frontend
npm install
npx playwright install chromium          # one-time browser download
E2E_BASE_URL=http://localhost:8080 npm run e2e
npm run e2e:report                        # open the HTML report
```

Screenshots land in `frontend/e2e/screenshots/`. The spec lives in
`frontend/e2e/rackmon.spec.ts` and is easy to extend.

---

## API surface (v1)

Base path `/api/v1`. Highlights (full schema at `/docs`):

- `POST /auth/login` · `POST /auth/refresh` · `GET /auth/me`
- `GET/POST /devices`, `GET/PATCH/DELETE /devices/{id}`,
  `GET /devices/status`, `GET /devices/latest`, `POST/DELETE /devices/{id}/maintenance`
- `GET /metrics?device_id=&metric=&agg=raw|1m|5m|1h` · `GET /metrics/export`
- `GET /alerts`, `GET /alerts/history`, `POST /alerts/{id}/ack|resolve`
- `GET/POST /rules`, `PATCH/DELETE /rules/{id}`
- `POST /discovery/scan`, `POST /discovery/import` (network auto-discovery)
- `GET /reports/adhoc?from=&to=&device_ids=&fmt=pdf|json` (PDF report + SLA)
- `GET/POST /admin/users`, `PATCH/DELETE /admin/users/{id}`, `GET /admin/audit`
- `GET /overview` · `GET /health` · `GET /metrics` (Prometheus) ·
  `WS /api/v1/stream?token=…&topics=device.{id}`

---

## Project structure

```
rackmon/
├── backend/
│   ├── app/
│   │   ├── main.py            # app factory, lifespan, SPA serving, middleware
│   │   ├── config.py          # every setting, env-driven (the authoritative list)
│   │   ├── database.py models.py schemas.py security.py crypto.py deps.py
│   │   ├── routers/           # auth, devices, metrics, alerts, rules, admin, system, stream…
│   │   ├── services/          # poller, collector, alert_engine, notifier, scheduler, seed…
│   │   ├── plugins/           # notifier plugins loaded by RACKMON_PLUGINS_MODULES
│   │   └── static/            # built SPA (generated by the frontend build)
│   ├── tests/                 # pytest suite
│   └── requirements.txt  pyproject.toml  Dockerfile
├── frontend/
│   ├── src/
│   │   ├── pages/             # Overview, Devices, DeviceDetail, Alerts, Reports, Admin, Login…
│   │   ├── components/        # Layout, RackElevation, LineChart, Sparkline, StatusBadge…
│   │   └── api.ts auth.tsx prefs.tsx hooks.ts types.ts lib/thermal.ts
│   ├── e2e/                   # Playwright, three engines
│   └── package.json  vite.config.ts  tailwind.config.js
├── deploy/
│   ├── Caddyfile              # TLS-terminating reverse proxy
│   ├── helm/rackmon/          # Helm chart (CI installs it on a real kind cluster)
│   └── timescale/             # extension + hypertable SQL
├── snmp-profiles/             # per-vendor OID sets: Dell iDRAC, HPE iLO, APC, Cisco, Juniper…
├── alerts/examples.yaml       # example rules with hold-down windows
├── unraid/rackmon.xml         # Unraid Community Applications template
├── scripts/                   # release.py, cross-browser and Kubernetes verification
├── docs/AUTO-UPDATE.md        # how the opt-in update check works
├── docker-compose.yml         # TimescaleDB + Caddy
├── docker-compose.sqlite.yml  # single container, nothing else running
└── .env.example               # every RACKMON_ variable, with its real default
```

---

## What it does

The short version of the feature list. Everything below is in the one edition
you download, and everything below is covered by the test suites — with the
honest exception of the handful of paths that need real hardware or a real
directory to exercise, which are called out where they appear.

**Monitoring & data**
- SNMP polling with a deterministic simulator *and* a real pysnmp collector
  (SNMP v1/v2c and **v3** with encrypted credentials)
- **SNMP trap reception** (handler tested; the UDP listener is opt-in and needs
  a real socket/devices)
- **Network auto-discovery** (scan a CIDR/range, import found hosts)
- **Per-vendor templates** (Dell/HPE/APC/generic) to create devices in one step
- Time-series storage with raw + 1m/5m/1h aggregation, CSV/JSON export
- **Statistical anomaly detection** (z-score)

**Alerting**
- Full engine: persistence windows, dedup, severity, throttle, auto-resolve,
  maintenance windows, tag/device/global scope
- **Correlation** (group active alerts by rack into incidents)
- **Escalation** (notify on-call when an alert stays unacknowledged)
- Notifications: console + SMTP email + **webhook / Slack / Teams / Telegram**,
  plus a **plugin system** for custom channels

**Reporting**
- Ad-hoc **PDF reports** with availability estimate and time-over-threshold (SLA)
- **Scheduled weekly** PDF report, auto-emailed

**Access & security**
- JWT + refresh, Argon2id, **TOTP MFA**, login lockout, RBAC, full audit log
- **API keys** for programmatic access
- **SSO via OpenID Connect** and **LDAP / Active Directory** (provisioning tested;
  the handshake needs a real IdP/directory)

**Frontend (React SPA)**
- Dashboard with the signature **rack thermal map**, devices, device detail
  (live + history + anomalies + timeline notes + maintenance), alerts (+incidents),
  rules, reports, discovery, **device comparison**, admin (users / API keys /
  backup / runtime settings / audit), **kiosk mode**, EN/ES i18n, light/dark themes

**Operations & deploy**
- `/health`, Prometheus `/metrics`, structured logs, retention sweeps
- **Config backup / restore**
- **Docker Compose** stack (Caddy + API + TimescaleDB + Redis) and TimescaleDB DDL
- **Helm chart** for Kubernetes: autoscaled API, a dedicated poller worker,
  TimescaleDB, Redis and Ingress/TLS. CI installs it onto a real `kind` cluster
  on every push and waits for the pods to come up, so it is not just YAML that
  parses.

**Not included**
- A hosted **plugin marketplace** (the plugin *mechanism* is implemented; a
  public catalog/store is out of scope).

> **No hardware? Nothing is hidden from you.** The built-in SNMP simulator is on
> by default, so every screen, alert, report and status page works end to end on
> a laptop with no network. The paths that genuinely need something real — SNMP
> against physical devices, SSO against an identity provider, LDAP against a
> directory — have scripts in `backend/scripts/integration/` that stand the real
> thing up locally; see [TESTING.md](TESTING.md).

---

## Security notes

- Set strong `RACKMON_JWT_SECRET` and `RACKMON_MASTER_KEY` before any real use;
  the defaults are obvious placeholders.
- SNMP community strings are encrypted at rest (AES-256-GCM) and never returned
  by the API (`has_community` boolean only).
- Passwords are hashed with Argon2id; login has lockout after repeated failures.
- Put the app behind TLS in production (the Caddyfile shows the one-line change
  for automatic HTTPS with a real domain), and bind the container port to
  `127.0.0.1` so the proxy is the only thing that can reach it.
- [SECURITY.md](SECURITY.md) has the hardening checklist and how to report a
  vulnerability privately. Every past advisory, with what it actually exposed, is
  listed at <https://rackmon.app/security.html#advisories> — including one that
  affected every release up to 1.2.9.

---

## Contributing

Issues and pull requests are welcome, and small ones are the most useful: a
vendor OID that does not match what your hardware actually returns, a threshold
that is wrong for your room, a sentence in the docs that sent you the wrong way.

- **Found a bug?** [Open an issue](https://github.com/rackmonsoftware-star/rackmon/issues).
  Include what you expected, what happened, and the vendor and model if it is
  about a reading.
- **Adding a vendor?** A tested OID for hardware I do not own is the single most
  valuable contribution to this project. There are two places and they should
  agree: `backend/app/services/templates.py` is the table the product polls from,
  and `snmp-profiles/*.yaml` is the standalone reference anyone can use with any
  tool. Both carry the scaling factor and the sentinel each vendor returns for "I
  cannot read this", which is where most of the mistakes live.
- **Changing behaviour?** Please bring a test. The convention here is that a test
  for a fix must fail with the fix removed — otherwise it documents nothing. See
  [TESTING.md](TESTING.md).

Run the suites before you open a PR:

```bash
cd backend  && python -m pytest -q
cd frontend && npm test
```

## Who made this

Built and maintained by **Enrique González Romero**
([LinkedIn](https://www.linkedin.com/in/enrique-gonz%C3%A1lez-romero-1b6a90275)).

RackMon started because a rack full of working hardware can cook itself while the
monitoring dashboard stays green, and because the tools that could have caught it
were a weekend of templates away from being useful. It is free, all of it, for
anyone who has that problem.

If it saves you a bad night, a star on this repository helps more than you would
think — it is how other people with hot racks find it.

## License

MIT — see [LICENSE](LICENSE). Use it, change it, run it for clients, fork it.
Copyright © 2026 Enrique González Romero.
