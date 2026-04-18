import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E configuration.
 *
 * Tests run against the full Docker Compose stack (real services — no mocking).
 * The base URL defaults to http://localhost:3000 but can be overridden via the
 * E2E_BASE_URL environment variable for staging/demo environments.
 *
 * Run locally:
 *   docker compose up -d
 *   npx playwright test
 *
 * Run a single spec:
 *   npx playwright test tests/e2e/public-site.spec.ts
 *
 * Show the HTML report:
 *   npx playwright show-report
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false, // Sequential — tests share a live backend; avoid race conditions
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",

  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    // Give slow CI environments more time
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
