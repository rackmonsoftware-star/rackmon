import { defineConfig, devices } from "@playwright/test";

// Runs against a RackMon instance you already have up (docker compose or local).
// Point it at your server with E2E_BASE_URL (defaults to the Compose URL).
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: [["list"], ["html", { open: "never", outputFolder: "e2e/report" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:8080",
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    // Real Gecko (Firefox) and WebKit (Safari's engine) coverage. Playwright
    // downloads these engines on CI runners, where the browser CDN is reachable.
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
