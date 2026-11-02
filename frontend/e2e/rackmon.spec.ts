import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";

/**
 * End-to-end visual + functional walkthrough of RackMon.
 *
 * Prerequisites:
 *   1. RackMon running (e.g. `docker compose up` -> http://localhost:8080)
 *   2. cd frontend && npm install && npx playwright install chromium
 *   3. E2E_BASE_URL=http://localhost:8080 npx playwright test
 *
 * Screenshots are written to frontend/e2e/screenshots/, and an HTML report to
 * frontend/e2e/report/ (open with `npx playwright show-report e2e/report`).
 */

const SHOTS = "e2e/screenshots";
fs.mkdirSync(SHOTS, { recursive: true });
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

async function login(page: Page) {
  await page.goto("/login");
  await page.locator('input[type="email"]').fill("admin@rackmon.io");
  await page.locator('input[type="password"]').fill("admin12345");
  await shot(page, "01-login");
  await page.locator('button[type="submit"]').click();
  // Redirected off the login page into the app.
  await expect(page).not.toHaveURL(/\/login/);
  await expect(page.locator("#root")).toBeVisible();
  await page.waitForTimeout(1500); // let live polling populate
}

test("login works and lands on the dashboard", async ({ page }) => {
  await login(page);
  await shot(page, "02-overview");
  // The dashboard renders temperature stats (mono numbers with a degree sign).
  await expect(page.getByText(/°/).first()).toBeVisible();
});

test("walks every page and captures screenshots", async ({ page }) => {
  await login(page);
  const routes: Array<[string, string]> = [
    ["/devices", "03-devices"],
    ["/alerts", "04-alerts"],
    ["/reports", "05-reports"],
    ["/compare", "06-compare"],
    ["/discover", "07-discover"],
    ["/admin", "08-admin"],
    ["/kiosk", "09-kiosk"],
  ];
  for (const [path, name] of routes) {
    await page.goto(path);
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(1000);
    await expect(page.locator("#root")).toBeVisible();
    await shot(page, name);
  }
});

test("opens a device and shows live telemetry", async ({ page }) => {
  await login(page);
  await page.goto("/devices");
  await page.waitForTimeout(1200);
  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toBeVisible();
  await rows.first().click();
  await page.waitForTimeout(1500);
  // Device detail shows metric cards and a history section.
  await expect(page.getByText(/°/).first()).toBeVisible();
  await shot(page, "10-device-detail");
});

test("runs a network discovery scan", async ({ page }) => {
  await login(page);
  await page.goto("/discover");
  await page.waitForTimeout(800);
  // The scan button is the primary button on the page.
  const scanBtn = page.locator("button.btn-primary").first();
  await scanBtn.click();
  await page.waitForTimeout(1500);
  // Results table should appear with discovered hosts.
  await expect(page.locator("table")).toBeVisible();
  await shot(page, "11-discovery-results");
});

test("compares a metric across devices", async ({ page }) => {
  await login(page);
  await page.goto("/compare");
  await page.waitForTimeout(1000);
  // Tick the first two device checkboxes in the selector.
  const checks = page.locator('input[type="checkbox"]');
  const n = Math.min(2, await checks.count());
  for (let i = 0; i < n; i++) await checks.nth(i).check();
  await page.waitForTimeout(1500);
  await shot(page, "12-compare");
});
