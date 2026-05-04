/**
 * M8-04 — Deterministic export failure injection E2E test.
 *
 * Tests the export failure → retry → success flow using deterministic backend
 * failure injection (EXPORT_TASK_FORCE_FAIL=true + arm-failure endpoint).
 *
 * Acceptance criteria covered:
 * - Deterministic backend failure injection is observable from the frontend.
 * - UI shows an error state when the export task reports FORCED_FAILURE.
 * - UI recovers correctly on retry after the one-shot failure is consumed.
 * - Full failure → retry → success flow is exercised in a single test run.
 *
 * Skip conditions:
 * - These tests are automatically skipped when EXPORT_TASK_FORCE_FAIL is not
 *   enabled in the backend (the arm-failure endpoint returns 404).  Run with
 *   EXPORT_TASK_FORCE_FAIL=true in the backend environment to exercise this
 *   spec (see docs/architecture/configuration.md and local-dev usage below).
 *
 * Local dev usage:
 *   EXPORT_TASK_FORCE_FAIL=true in your .env (or docker-compose override) and
 *   restart the backend + worker containers, then run:
 *     npx playwright test mx8-04-export-failure-injection
 *
 * CI usage:
 *   Add EXPORT_TASK_FORCE_FAIL=true to .env.ci (or the relevant CI env file)
 *   for the E2E shard that runs this spec.  All other tests are unaffected when
 *   the one-shot arm endpoint is not called.
 *
 * Security:
 * - No student PII in any fixture — synthetic names and IDs only.
 * - No credential-format strings — all test credentials are clearly synthetic.
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { seedLockedGrades } from "./helpers";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

/** Call the test-only arm-failure endpoint.  Returns true on success. */
async function armExportFailure(token: string): Promise<boolean> {
  const res = await fetch(
    `${API_BASE}/api/v1/internal/export-test-controls/arm-failure`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    },
  );
  return res.ok;
}

/** Call the test-only disarm endpoint (teardown safety). */
async function disarmExportFailure(token: string): Promise<void> {
  await fetch(
    `${API_BASE}/api/v1/internal/export-test-controls/arm-failure`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    },
  ).catch(() => {
    // Ignore errors during teardown — the endpoint may already be unavailable.
  });
}

/** Probe whether the failure injection endpoint is available. */
async function isFailureInjectionAvailable(): Promise<boolean> {
  const res = await fetch(
    `${API_BASE}/api/v1/internal/export-test-controls/arm-failure`,
    { method: "DELETE" },
  ).catch(() => null);
  // Endpoint returns 200/401 when registered; 404 when EXPORT_TASK_FORCE_FAIL=false.
  // We treat any status other than 404 (including 401 Unauthorized) as "available"
  // because 401 confirms the router exists but requires auth.
  return res !== null && res.status !== 404;
}

// ---------------------------------------------------------------------------
// Journey 4 — Export failure injection: deterministic failure → retry success
// ---------------------------------------------------------------------------
test.describe("Journey 4 — Export failure injection (M8-04)", () => {
  test.describe.configure({ mode: "serial", timeout: 180_000 });
  test.setTimeout(180_000);

  const state: {
    email: string;
    password: string;
    token: string;
    assignmentId: string;
    injectionAvailable: boolean;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    email: "",
    password: "",
    token: "",
    assignmentId: "",
    injectionAvailable: false,
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(180_000);

    // Probe whether the arm-failure endpoint is reachable.  If not, all tests
    // in this describe block will be skipped via the per-test skip guard.
    state.injectionAvailable = await isFailureInjectionAvailable();
    if (!state.injectionAvailable) {
      return;
    }

    // Seed locked grades for the export flow.
    const fixture = await seedLockedGrades("m8-04-failure-injection");
    state.email = fixture.email;
    state.password = fixture.password;
    state.assignmentId = fixture.assignmentId;

    // Log in via the API to get a token for the arm-failure call.
    const loginRes = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: state.email, password: state.password }),
    });
    if (!loginRes.ok) {
      throw new Error(`Login failed: ${loginRes.status}`);
    }
    const loginBody = (await loginRes.json()) as { data: { access_token: string } };
    state.token = loginBody.data.access_token;

    // Create browser context and log in via the UI form.
    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
      acceptDownloads: true,
    });
    state.page = await state.context.newPage();

    await state.page.goto("/dashboard");
    await expect(state.page).toHaveURL(/\/login/);
    await state.page.getByLabel("Email").fill(state.email);
    await state.page.getByLabel("Password").fill(state.password);
    await state.page.getByRole("button", { name: /sign in/i }).click();
    await expect(state.page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  test.afterAll(async () => {
    // Safety: clear any lingering armed failure flag so it does not bleed into
    // other test specs.
    if (state.injectionAvailable) {
      await disarmExportFailure(state.token);
    }
    await state.context?.close();
  });

  // ── Test 1: Failure injection endpoint is available ──────────────────────

  test("failure injection: arm-failure endpoint is reachable when EXPORT_TASK_FORCE_FAIL=true", async () => {
    test.skip(
      !state.injectionAvailable,
      "EXPORT_TASK_FORCE_FAIL is not enabled — skipping failure injection tests",
    );

    // Arm and immediately disarm to verify the endpoint round-trips correctly.
    const armed = await armExportFailure(state.token);
    expect(armed).toBe(true);
    await disarmExportFailure(state.token);
  });

  // ── Test 2: Forced failure produces failure UI ────────────────────────────

  test("failure injection: export UI shows error state when task force-fails", async () => {
    test.skip(
      !state.injectionAvailable,
      "EXPORT_TASK_FORCE_FAIL is not enabled — skipping failure injection tests",
    );
    if (!state.page) throw new Error("Browser context not initialized");
    const page = state.page;

    await page.goto(`/dashboard/assignments/${state.assignmentId}`);

    // Wait for the export button to appear.
    const exportButton = page.getByRole("button", { name: /export options/i });
    await expect(exportButton).toBeVisible({ timeout: 15_000 });

    // Arm the one-shot failure flag.
    const armed = await armExportFailure(state.token);
    expect(armed).toBe(true);

    // Open the export menu.
    await exportButton.click();

    const pdfButton = page.getByRole("menuitem", {
      name: /export feedback as pdf zip/i,
    });
    await expect(pdfButton).toBeEnabled({ timeout: 5_000 });

    // Trigger the export — the one-shot flag will cause the Celery task to fail.
    await pdfButton.click();

    // The ExportPanel should poll the status endpoint and transition to the
    // failure state once the task returns FORCED_FAILURE.
    // Allow up to 60 s for the Celery worker to run the task and write the
    // failed status back to Redis.
    const exportFailedMessage = page.getByRole("alert").filter({ hasText: /export failed/i });
    await expect(exportFailedMessage).toBeVisible({ timeout: 60_000 });
  });

  // ── Test 3: Retry succeeds after one-shot is consumed ────────────────────

  test("failure injection: retry export succeeds after one-shot failure is consumed", async () => {
    test.skip(
      !state.injectionAvailable,
      "EXPORT_TASK_FORCE_FAIL is not enabled — skipping failure injection tests",
    );
    if (!state.page) throw new Error("Browser context not initialized");
    const page = state.page;

    // The previous test consumed the one-shot key.  Navigate back to ensure
    // the ExportPanel is in its initial (idle) state before triggering retry.
    await page.goto(`/dashboard/assignments/${state.assignmentId}`);

    const exportButton = page.getByRole("button", { name: /export options/i });
    await expect(exportButton).toBeVisible({ timeout: 15_000 });
    await exportButton.click();

    const pdfButton = page.getByRole("menuitem", {
      name: /export feedback as pdf zip/i,
    });
    await expect(pdfButton).toBeEnabled({ timeout: 5_000 });

    // Trigger the retry export.  The one-shot flag was consumed in Test 2 so
    // this export should proceed normally and reach a terminal "complete" state.
    await pdfButton.click();

    // The ExportPanel polls until the task completes.  Accept either the
    // transient "Export in progress" text or the final download link as
    // confirmation that the retry started.
    const progressText = page.getByText(/export in progress/i);
    const downloadLink = page.getByRole("link", {
      name: /download the exported pdf zip file/i,
    });
    await expect
      .poll(
        async () =>
          (await progressText.isVisible()) || (await downloadLink.isVisible()),
        { timeout: 15_000 },
      )
      .toBe(true);

    // Wait for the download link to appear — confirms the export completed
    // successfully after the one-shot failure was consumed.
    await expect(downloadLink).toBeVisible({ timeout: 120_000 });

    // Verify the link has a non-empty href (valid pre-signed URL from backend).
    const href = await downloadLink.getAttribute("href");
    expect(href).toBeTruthy();
    expect(href).toMatch(/\S/);
  });
});
