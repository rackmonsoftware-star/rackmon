# Changelog

Changes to this deployment kit. For the application's own changelog see
<https://rackmon.app/changelog.html>.

## 2026-09-08

- First public release of the deployment kit.
- Added the SNMP temperature OID reference: RFC 3433 standard, Cisco, Juniper,
  Dell iDRAC, HPE iLO, APC/Schneider NMC — with scaling and units gotchas documented.
- Added `docker-compose.yml` (TimescaleDB + Caddy) and `docker-compose.sqlite.yml`
  (single container) using the published image.
- Added a fully commented `.env.example` covering every `RACKMON_` variable.
- Added Unraid Community Applications template.
- Added example alerting rules with hold-down windows.
