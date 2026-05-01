/**
 * E2E Journey 7 — Resubmission Loop (MX.7b).
 *
 * Covers the full resubmission loop teacher journey end-to-end against the
 * real Docker Compose stack.  No MSW — all requests hit the actual backend.
 *
 * Journey flow:
 *   1. Fixture seeds one student, grades and locks the original essay, submits a
 *      resubmission, re-grades and locks the revision, and confirms the skill
 *      profile is updated before the tests run.
 *   2. Teacher opens the essay review page for the resubmitted essay.
 *   3. "Revision Comparison" section is visible with the "Resubmitted" badge.
 *   4. Version history strip shows "Version 1 (Original)" and "Version 2 (Revised)"
 *      buttons; teacher can switch between them.
 *   5. Score deltas are visible per criterion in the criterion deltas table.
 *   6. Total score delta summary is visible.
 *   7. Feedback-addressed indicators render (or the section is absent when the
 *      LLM step was skipped — both are valid; the test checks structural presence).
 *   8. Side-by-side diff placeholder is visible with "Original submission" and
 *      "Revised submission" column headers.
 *   9. Student profile shows skill data (progress bars) after the resubmission.
 *
 * Acceptance criteria (from issue MX.7b):
 * - Journey covers: original grade locked, resubmission submitted, re-grade runs,
 *   teacher opens side-by-side diff view.
 * - Test verifies score deltas are visible per criterion.
 * - Test verifies feedback-addressed indicators render correctly.
 * - Test verifies version history list and snapshot switching.
 * - Improvement signal appears in student profile after resubmission.
 * - No assertions on exact essay content — test structure and behavior only.
 *
 * Depends on: M6-12 (#193) — Resubmission UI
 *
 * Security:
 * - No student PII in any fixture value — synthetic names and IDs only.
 * - No credential-format strings — all test credentials are clearly synthetic.
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { clearMailpit, seedResubmissionFixture } from "./helpers";
import type { ResubmissionFixture } from "./helpers";

// ---------------------------------------------------------------------------
// Journey 7: Resubmission Loop
// ---------------------------------------------------------------------------
test.describe("Journey 7 — Resubmission Loop", () => {
  // All steps share a single browser context (auth cookie, fixture IDs) and
  // must run in declaration order.
  test.describe.configure({ mode: "serial", timeout: 600_000 });

  // Shared state populated in beforeAll.
  const state: {
    fixture: ResubmissionFixture | null;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    fixture: null,
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    // seedResubmissionFixture runs two full grading cycles (up to 120 s each)
    // and several polling loops before returning — the describe-level timeout
    // of 600 s applies to all hooks and tests.
    await clearMailpit();

    // Seed the full fixture:
    //   teacher → class → 1 student → rubric → assignment (resubmission enabled)
    //   → original essay → grade → lock
    //   → resubmission → re-grade → lock revision
    //   → skill profile updated (assignment_count >= 1)
    state.fixture = await seedResubmissionFixture("journey7");

    // Create a browser context and log in via the UI form so the browser
    // holds a valid httpOnly refresh_token cookie for all subsequent tests.
    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();

    const page = state.page;
    await page.goto("/dashboard");
    // Middleware redirects unauthenticated requests to /login.
    await expect(page).toHaveURL(/\/login/);
    await page.getByLabel("Email").fill(state.fixture.email);
    await page.getByLabel("Password").fill(state.fixture.password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  // ── Test 1: Review page renders the Revision Comparison section ────────────

  test("review page shows the Revision Comparison section for a resubmitted essay", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // Navigate directly to the essay review page.
    await page.goto(
      `/dashboard/assignments/${state.fixture.assignmentId}/review/${state.fixture.essayId}`,
    );

    // Wait for the page to load (grade data must arrive before the panel renders).
    await expect(
      page.getByRole("heading", { level: 1 }),
    ).toBeVisible({ timeout: 20_000 });

    // The ResubmissionPanel renders a "Revision Comparison" heading (h2).
    await expect(
      page.getByRole("heading", { name: /revision comparison/i }),
    ).toBeVisible({ timeout: 30_000 });

    // The "Resubmitted" badge should also be visible alongside the heading.
    await expect(page.getByText(/resubmitted/i)).toBeVisible({ timeout: 10_000 });
  });

  // ── Test 2: Version history strip renders and is interactive ───────────────

  test("version history strip renders Version 1 and Version 2 buttons and supports switching", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // The version history strip has aria-label="Version history".
    const versionStrip = page.getByLabel("Version history");
    await expect(versionStrip).toBeVisible({ timeout: 15_000 });

    // Both version buttons must be present.
    const v1Button = versionStrip.getByRole("button", {
      name: /version 1.*original/i,
    });
    const v2Button = versionStrip.getByRole("button", {
      name: /version 2.*revised/i,
    });

    await expect(v1Button).toBeVisible({ timeout: 10_000 });
    await expect(v2Button).toBeVisible({ timeout: 10_000 });

    // By default the revised version (v2) is active (aria-pressed=true).
    await expect(v2Button).toHaveAttribute("aria-pressed", "true");
    await expect(v1Button).toHaveAttribute("aria-pressed", "false");

    // Click "Version 1 (Original)" — it should become active.
    await v1Button.click();
    await expect(v1Button).toHaveAttribute("aria-pressed", "true");
    await expect(v2Button).toHaveAttribute("aria-pressed", "false");

    // Restore to revised view for subsequent tests.
    await v2Button.click();
    await expect(v2Button).toHaveAttribute("aria-pressed", "true");
  });

  // ── Test 3: Score deltas visible per criterion ─────────────────────────────

  test("criterion score changes table is visible with per-criterion deltas", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // The "Criterion Score Changes" section heading (h3).
    await expect(
      page.getByRole("heading", { name: /criterion score changes/i }),
    ).toBeVisible({ timeout: 15_000 });

    // The criterion deltas list (aria-label="Criterion score changes") must
    // contain at least one list item — one per criterion in the rubric.
    const deltasList = page.getByRole("list", {
      name: /criterion score changes/i,
    });
    await expect(deltasList).toBeVisible({ timeout: 10_000 });

    const deltaItems = deltasList.getByRole("listitem");
    // seedRubric always creates 2 criteria, so at least 2 items are expected.
    await expect(deltaItems).toHaveCount(2);

    // Each criterion row must show a base score, arrow, and revised score.
    // We check structure (the "→" separator) without asserting exact numbers.
    const firstItem = deltaItems.first();
    await expect(firstItem.getByText(/→/)).toBeVisible({ timeout: 10_000 });
  });

  // ── Test 4: Total score delta summary is visible ────────────────────────────

  test("total score delta summary is visible", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // ScoreDeltaSummary renders "Total score change" with a badge.
    await expect(page.getByText(/total score change/i)).toBeVisible({
      timeout: 15_000,
    });

    // The badge carries an aria-label of "Total score delta: ±N".
    // We only assert the aria-label exists (not the exact number) to stay
    // independent of LLM scoring output.
    const deltaBadge = page.locator(
      '[aria-label^="Total score delta:"]',
    );
    await expect(deltaBadge).toBeVisible({ timeout: 10_000 });
  });

  // ── Test 5: Feedback-addressed indicators render correctly ─────────────────

  test("feedback-addressed indicators are present or section is absent (LLM best-effort)", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // `hasFeedbackAddressed` is determined by querying the revision-comparison
    // API during fixture setup and reflects whether the LLM step produced
    // non-null feedback_addressed data.  This lets us differentiate between
    // "the UI failed to render data that exists" (a real failure) and "the LLM
    // step was skipped so there is nothing to show" (a valid outcome).

    const feedbackLegend = page.getByText(
      /feedback addressed indicators are generated by ai/i,
    );
    const feedbackAddressedBtn = page
      .getByRole("button", { name: /feedback (not )?addressed/i })
      .first();

    if (state.fixture.hasFeedbackAddressed) {
      // The backend has feedback_addressed data — the UI must render the
      // legend note and/or at least one feedback-addressed indicator button.
      await expect(
        feedbackLegend.or(feedbackAddressedBtn),
      ).toBeVisible({ timeout: 15_000 });

      // Exercise the expand/collapse interaction on the first feedback button
      // when it is visible.
      const btnVisible = await feedbackAddressedBtn.isVisible();
      if (btnVisible) {
        await feedbackAddressedBtn.click();
        await expect(
          page.getByText(/feedback given/i).first(),
        ).toBeVisible({ timeout: 10_000 });

        await feedbackAddressedBtn.click();
        await expect(
          page.getByText(/feedback given/i).first(),
        ).not.toBeVisible({ timeout: 5_000 });
      }
    } else {
      // The LLM step was skipped — neither the legend nor any indicator
      // button should be present in the DOM.
      await expect(feedbackLegend).not.toBeVisible({ timeout: 5_000 });
      await expect(feedbackAddressedBtn).not.toBeVisible();
    }
  });

  // ── Test 6: Side-by-side diff placeholder is visible ──────────────────────

  test("side-by-side diff placeholder renders Original and Revised columns", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // DiffPlaceholder renders two column headers.
    await expect(page.getByText("Original submission", { exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Revised submission", { exact: true })).toBeVisible({
      timeout: 10_000,
    });

    // After Test 2 restored us to v2, the "Revised submission" column header
    // should carry text-blue-700 (active) and "Original submission" should
    // carry text-gray-600 (inactive).  These classes are stable signals from
    // DiffPlaceholder that the active column prop is applied correctly.
    const revisedHeader = page.getByText("Revised submission", { exact: true });
    const originalHeader = page.getByText("Original submission", { exact: true });
    await expect(revisedHeader).toHaveClass(/text-blue-700/, { timeout: 10_000 });
    await expect(originalHeader).toHaveClass(/text-gray-600/);
  });

  // ── Test 7: Version history snapshot switching changes active column ────────

  test("switching version history selection highlights the correct diff column", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    const versionStrip = page.getByLabel("Version history");

    // Switch to Version 1 — "Original submission" header should become
    // text-blue-700 (active) and "Revised submission" should become
    // text-gray-600 (inactive).
    const v1Button = versionStrip.getByRole("button", {
      name: /version 1.*original/i,
    });
    await v1Button.click();
    await expect(v1Button).toHaveAttribute("aria-pressed", "true");

    const originalHeader = page.getByText("Original submission", { exact: true });
    const revisedHeader = page.getByText("Revised submission", { exact: true });
    await expect(originalHeader).toHaveClass(/text-blue-700/, { timeout: 10_000 });
    await expect(revisedHeader).toHaveClass(/text-gray-600/);

    // Switch back to Version 2 — "Revised submission" becomes active again.
    const v2Button = versionStrip.getByRole("button", {
      name: /version 2.*revised/i,
    });
    await v2Button.click();
    await expect(v2Button).toHaveAttribute("aria-pressed", "true");
    await expect(revisedHeader).toHaveClass(/text-blue-700/, { timeout: 10_000 });
    await expect(originalHeader).toHaveClass(/text-gray-600/);
  });

  // ── Test 8: Student profile shows skill data after resubmission ─────────────

  test("student profile page shows skill data after resubmission grade is locked", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // Navigate to the student profile page.
    await page.goto(
      `/dashboard/students/${state.fixture.studentId}`,
    );

    // The "Skill Profile" heading must be visible.
    await expect(
      page.getByRole("heading", { name: /skill profile/i }),
    ).toBeVisible({ timeout: 20_000 });

    // At least one SkillBar progress bar should be visible — confirming that
    // the skill profile was computed from the locked grade(s).
    await expect(
      page.getByRole("progressbar").first(),
    ).toBeVisible({ timeout: 20_000 });

    // Growth indicators (improving / stable / declining) reflect the skill
    // trend.  The backend returns "stable" when only one assignment contributes,
    // so a trend badge is always rendered by StudentProfile regardless of
    // direction.  We only assert that at least one badge is present rather than
    // asserting a specific direction, which would couple the test to LLM output.
    const trendPatterns = [/improving/i, /stable/i, /declining/i];
    let anyTrendVisible = false;
    for (const pattern of trendPatterns) {
      if (await page.getByText(pattern).first().isVisible()) {
        anyTrendVisible = true;
        break;
      }
    }
    expect(anyTrendVisible).toBe(true);
  });
});
