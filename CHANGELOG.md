# Changelog

Release-by-release, newest first. The long-form version, with what each defect
actually did to the people running it, is at <https://rackmon.app/changelog.html>.

## 1.3.0 — 2 November 2026

**RackMon is now free and open source under the MIT licence, and this repository
holds the whole thing: backend, frontend and tests.** Until today it shipped as a
container image with the source closed and five features behind a paid key.

- **The five paid features are simply in the product**: SSO (OIDC), LDAP / Active
  Directory, the public status page, SLA and availability PDF reports, and
  white-label branding. Six checks in the request path are gone, along with the
  device limit. No edition, no tier, no key to verify — the signature-checking
  code was removed rather than left in place deciding nothing.
- **Why**: in several months the open-core model produced twenty-two
  installations and zero sales. The problem was never the price.
- **Nothing breaks on upgrade.** `RACKMON_LICENSE_KEY` is still read and now
  ignored, so an existing `.env` starts untouched. `GET /api/v1/license` still
  answers, reporting one edition with everything enabled.
- **Security — the factory administrator came back on every restart.** The seeder
  recreated the admin account whenever its configured email was missing, so the
  two normal ways of retiring it (renaming it to your own address, or creating
  your own and deleting it) each handed the next restart a brand-new active admin
  carrying the default password. The production guard did not cover it: it only
  rejects a factory `RACKMON_ADMIN_PASSWORD` when
  `RACKMON_ENVIRONMENT=production`, and that is `development` unless you set it.
  The account is now seeded only when the installation has no administrator at
  all, deactivated ones included.
- The admin panel's update-manifest placeholder, and `scripts/release.py`'s
  default release URL, both still pointed at `rackmon.io` — a domain this project
  does not own. Fixed, and the test that guards it now walks the whole repository
  instead of just `backend/app`.
- The settings and reports screens still labelled three included features "Pro",
  and only drew them when `GET /api/v1/license` succeeded — so a failed request
  showed a padlock over something free. Removed.
- The deployment kit that used to live here on its own is now part of this
  repository: compose files, Helm chart, Caddyfile, Unraid template, SNMP
  profiles and example alert rules. The Helm chart moved from `helm/rackmon` to
  `deploy/helm/rackmon`.

## 1.2.10 — 1 November 2026

Security release. **Upgrade this one.**

- **Arbitrary file read, no account needed, in every version up to and including
  1.2.9.** The route serving the web app joined the request path onto the static
  directory without normalising it, so an encoded `../` walked out and returned
  any file the process could read — including the `.env` with
  `RACKMON_JWT_SECRET` and `RACKMON_MASTER_KEY`. If your instance was reachable
  from a network you do not trust, **rotate both secrets** and re-enter your SNMP
  credentials afterwards.
- The default update-manifest URL pointed at `rackmon.io`, a domain this project
  does not own and which does not resolve, so no installation ever received an
  announcement — including an announcement about the entry above.

## 2026-09-08

First public release of the deployment kit (then a repository of its own).

- SNMP temperature OID reference: RFC 3433 standard, Cisco, Juniper, Dell iDRAC,
  HPE iLO, APC/Schneider NMC — with the scaling and units gotchas documented.
- `docker-compose.yml` (TimescaleDB + Caddy) and `docker-compose.sqlite.yml`
  (single container).
- A fully commented `.env.example`, the Unraid Community Applications template,
  and example alerting rules with hold-down windows.
