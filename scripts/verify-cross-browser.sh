#!/usr/bin/env bash
#
# Cross-browser E2E: runs the RackMon end-to-end suite on Chromium, Firefox AND
# WebKit (Safari's engine) — five tests per engine, fifteen runs in all.
#
# Requirements: Node 18+, Python 3.11+, and network access the first time, to
#               download the browser engines.
# Usage:        bash scripts/verify-cross-browser.sh
#
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "==> [1/5] Backend dependencies"
cd "$ROOT/backend"
python3 -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q -r requirements.txt

echo "==> [2/5] Building the frontend (outputs into backend/app/static)"
cd "$ROOT/frontend"
npm ci
npm run build

echo "==> [3/5] Installing Playwright engines: Chromium, Firefox, WebKit"
npx playwright install --with-deps chromium firefox webkit

echo "==> [4/5] Starting the backend (serves API + the built SPA on :8000)"
cd "$ROOT/backend"
RACKMON_SEED_DEMO_DATA=true RACKMON_JWT_SECRET=dev RACKMON_MASTER_KEY=dev-master-key \
  nohup uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/rackmon-e2e.log 2>&1 &
BACK=$!
trap 'kill $BACK 2>/dev/null || true' EXIT
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1 && break; sleep 1; done

echo "==> [5/5] Running Playwright on all three engines"
cd "$ROOT/frontend"
E2E_BASE_URL=http://127.0.0.1:8000 npx playwright test
echo ""
echo "Done. HTML report: frontend/e2e/report/index.html"
echo "(15 runs = 5 tests x {chromium, firefox, webkit})"
