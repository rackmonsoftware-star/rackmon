# Testing RackMon

Everything here runs on your own machine, and most of it runs on every push via
[`.github/workflows/ci.yml`](.github/workflows/ci.yml). Nothing needs real
hardware: a built-in SNMP simulator stands in for the devices, so the whole
suite works on a laptop with no network.

## The rule

**A test for a fix has to fail when the fix is removed.** Otherwise it documents
a belief rather than a behaviour, and it will keep passing long after the thing
it was meant to protect has rotted. When you fix something here, write the test,
put the bug back, watch it go red, then put the fix back.

That rule is why several files in `backend/tests/` read like small essays: the
docstring says what broke, who it would have hurt, and why the obvious-looking
version of the check does not catch it.

## Running it

```bash
cd backend
python -m pytest -q                  # the whole suite, on SQLite
python -m pytest tests/test_sla.py   # one file
python -m pyflakes app               # the lint CI runs
```

```bash
cd frontend
npm test                             # Vitest: components and logic
npm run typecheck                    # tsc --noEmit
npm run build                        # production build
```

The backend suite also runs against **PostgreSQL + Redis** when you point it at
them, which is what CI does on every push:

```bash
RACKMON_TEST_DATABASE_URL=postgresql+psycopg2://rackmon:rackmon@localhost:5432/rackmon \
RACKMON_TEST_REDIS_URL=redis://localhost:6379/15 \
python -m pytest -q
```

Without `RACKMON_TEST_REDIS_URL` the Redis round-trip test skips; everything else
runs identically on either database.

## End to end, in three real browsers

Playwright drives Chromium, Firefox and WebKit against a running instance —
login, a walk through every page, live telemetry, a discovery scan, and a metric
comparison. Five tests per engine.

```bash
bash scripts/verify-cross-browser.sh      # downloads the engines the first time
```

Or by hand, against an instance you already have up:

```bash
cd frontend
npx playwright install chromium firefox webkit
E2E_BASE_URL=http://localhost:8000 npx playwright test
npm run e2e:report
```

Screenshots of each step land in `frontend/e2e/screenshots/`, which is useful
when a layout change breaks something that still technically passes.

## On a real Kubernetes cluster

```bash
bash scripts/verify-k8s.sh     # needs Docker; installs kind and helm if missing
```

Creates a throwaway `kind` cluster, builds the image, `helm install`s the chart
and waits for the pods to be Ready. CI runs the same thing.

Note that the chart ships `change-me` placeholders on purpose and RackMon
**refuses to start** on them, so an install has to pass real values:

```bash
helm install rackmon ./deploy/helm/rackmon \
  --set secrets.jwtSecret="$(openssl rand -hex 32)" \
  --set secrets.masterKey="$(openssl rand -hex 32)" \
  --set secrets.adminPassword="$(openssl rand -hex 18)"
```

## Against real external systems

`backend/scripts/integration/` is for the paths a simulator cannot reach: SNMP
against a real agent, LDAP against a real directory, the OIDC flow against a
real identity provider. There is one script there today — the SNMP v2c check,
which is the one that caught the production collector importing a pysnmp API
that no longer exists — plus notes on how to stand up each of the others and
what each has found. None of it runs in CI.

## What the suites cover

| | |
|---|---|
| Backend | pytest, on SQLite and on PostgreSQL + Redis |
| Frontend | Vitest components and logic, plus `tsc` and a production build |
| End to end | Playwright on Chromium, Firefox and WebKit |
| Deployment | Helm install onto a real `kind` cluster |

There is also an **API↔frontend contract test** that pins every field the
interface reads, so a serialization change cannot quietly blank a screen, and a
set of tripwires that walk the source looking for things that must not come
back: a feature closed behind a licence, a URL pointing at a domain this project
does not own, a version that disagrees between the chart and the code, a compose
file that cannot start.
