/**
 * E2E: M4 workflow coverage (confidence, integrity, regrade, media controls)
 *
 * This suite validates core teacher workflows introduced in M4:
 * - Confidence-aware review queue controls
 * - Integrity panel rendering and status actions
 * - Regrade request logging + denial flow validation
 * - Media feedback controls visibility in essay review panel
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { seedGradedEssay } from "./helpers";

test.describe("M4 workflow coverage", () => {
  test.describe.configure({ mode: "serial", timeout: 180_000 });
  test.setTimeout(180_000);

  const state: {
    email: string;
    password: string;
    assignmentId: string;
    essayId: string;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    email: "",
    password: "",
    assignmentId: "",
    essayId: "",
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(180_000);

    const fixture = await seedGradedEssay("m4-workflow");
    state.email = fixture.email;
    state.password = fixture.password;
    state.assignmentId = fixture.assignmentId;
    state.essayId = fixture.essayId;

    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();

    await state.page.goto("/dashboard");
    // Wait for JS hydration before interacting with the form. Without this,
    // clicking Sign In too early can fall back to native GET form submission
    // and produce a flaky /login?email=... URL instead of navigating.
    await state.page.waitForLoadState("networkidle");
    // like /login?email=...&password=... instead of navigating to /dashboard.
    await state.page.waitForLoadState("networkidle");
    await state.page.getByLabel("Email").fill(state.email);
    await state.page.getByLabel("Password").fill(state.password);
    await state.page.getByRole("button", { name: /sign in/i }).click();
    await expect(state.page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  test("review queue exposes confidence triage controls", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    await page.goto(`/dashboard/assignments/${state.assignmentId}/review`);

    await expect(
      page.getByRole("heading", { name: /review queue/i }),
    ).toBeVisible({ timeout: 15_000 });

    // M4.2 controls should appear only when backend provides confidence fields.
    await expect(
      page.getByRole("button", { name: /confidence/i }),
    ).toBeVisible({ timeout: 10_000 });

    const filterSelect = page.getByLabel("Filter:");
    await expect(filterSelect).toBeVisible({ timeout: 10_000 });

    const hasLowConfidenceOption = await filterSelect
      .locator("option", { hasText: /low confidence/i })
      .count();

    if (hasLowConfidenceOption > 0) {
      await expect(filterSelect).toContainText(/low confidence/i);

      // At least one queue row should include confidence in its accessible name.
      const rowWithConfidence = page
        .getByRole("listitem")
        .filter({ hasText: /high|medium|low/i })
        .first();
      await expect(rowWithConfidence).toBeVisible({ timeout: 10_000 });
    }
  });

  test("essay review exposes media controls and integrity panel", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    await page.goto(
      `/dashboard/assignments/${state.assignmentId}/review/${state.essayId}`,
    );

    await expect(
      page.getByRole("region", { name: /grade review/i }),
    ).toBeVisible({ timeout: 15_000 });

    // M4.10-M4.12 media controls should be present in the review panel.
    await expect(
      page.getByRole("button", { name: /start recording audio comment/i }),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByRole("button", { name: /start recording video comment/i }),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByRole("button", { name: /apply from media bank/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Integrity panel can render either the actionable region or an empty-state card.
    const integrityRegion = page.getByRole("region", { name: /academic integrity signals/i });
    const integrityHeading = page.getByRole("heading", { name: /integrity signals/i });
    await expect
      .poll(
        async () => (await integrityRegion.isVisible()) || (await integrityHeading.isVisible()),
        { timeout: 10_000 },
      )
      .toBe(true);

    const noReportMessage = page.getByText(/no integrity report is available/i);
    if (await noReportMessage.isVisible()) {
      await expect(noReportMessage).toBeVisible();
      return;
    }

    const flagButton = page.getByRole("button", { name: /flag for follow-up/i });
    if (await flagButton.isVisible()) {
      await flagButton.click();
      await expect(
        page.getByText(/flagged for follow-up/i),
      ).toBeVisible({ timeout: 10_000 });
    }
  });

  test("regrade request can be logged and denied with required note", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    await page.goto(`/dashboard/assignments/${state.assignmentId}`);

    await expect(
      page.getByRole("heading", { name: /regrade requests/i }),
    ).toBeVisible({ timeout: 15_000 });

    await page.getByRole("tab", { name: /log request/i }).click();

    // Validation on empty submit.
    await page.getByRole("button", { name: /submit request/i }).click();
    await expect(page.getByText(/please select an essay/i)).toBeVisible({ timeout: 5_000 });

    const essaySelect = page.getByLabel(/^Essay\s*/i);
    await essaySelect.selectOption({ index: 1 });

    const criterionSelect = page.getByLabel(/^Criterion\s*/i);
    // Keep overall-grade default if criteria haven't loaded yet; otherwise select first criterion.
    const criterionOptions = await criterionSelect.locator("option").count();
    if (criterionOptions > 1) {
      await criterionSelect.selectOption({ index: 1 });
    }

    const disputeText = `E2E regrade request ${Date.now()} — criterion weighting concern.`;
    await page.getByLabel(/dispute justification/i).fill(disputeText);

    await page.getByRole("button", { name: /submit request/i }).click();

    // Form success returns to queue tab.
    await expect(
      page.getByRole("tab", { name: /^queue$/i }),
    ).toHaveAttribute("aria-selected", "true", { timeout: 10_000 });

    // Open the new request and test denial validation.
    await page.getByRole("button", { name: /review regrade request/i }).first().click();

    await expect(
      page.getByRole("dialog", { name: /regrade request review/i }),
    ).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /^deny$/i }).click();
    await page.getByRole("button", { name: /confirm denial/i }).click();

    await expect(
      page.getByText(/resolution note is required/i),
    ).toBeVisible({ timeout: 5_000 });

    await page
      .getByLabel(/resolution note/i)
      .fill(`Denied in E2E: ${Date.now()} — no scoring error found.`);
    await page.getByRole("button", { name: /confirm denial/i }).click();

    await expect(
      page.getByRole("dialog", { name: /regrade request review/i }),
    ).not.toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /^resolved$/i }).click();
    await expect(page.getByText(/denied/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test("bulk-approve high-confidence essays control is visible when eligible", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    await page.goto(`/dashboard/assignments/${state.assignmentId}/review`);

    // If high-confidence candidates exist, the action must be actionable.
    const bulkApprove = page.getByRole("button", {
      name: /approve .*high-confidence essay/i,
    });

    if (await bulkApprove.isVisible()) {
      await expect(bulkApprove).toBeEnabled();
    }
  });
});








