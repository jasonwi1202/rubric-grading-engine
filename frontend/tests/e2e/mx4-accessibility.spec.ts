/**
 * E2E: MX.4 — Accessibility audit (WCAG 2.1 AA)
 *
 * Implements the MX.4 acceptance criteria from docs/roadmap.md:
 *   - ARIA labels on all icon-only buttons, score inputs, and status badges
 *   - Focus management in every modal and dialog
 *   - Color contrast compliance (verified via axe-core)
 *   - Screen reader testing on grading interface: essay review panel, review
 *     queue, and export panel announced correctly
 *   - Playwright accessibility scan using @axe-core/playwright; fails on any
 *     critical or serious WCAG 2.1 AA violation
 *
 * Structure:
 *   - Block 1: Public pages — no auth required; always run
 *   - Block 2: Auth pages — login/signup; no auth required
 *   - Block 3: Grading interface — requires seeded teacher account and
 *     assignment; uses the seedLockedGrades helper from helpers.ts
 *
 * Security:
 *   - No student PII in any fixture value — synthetic names and IDs only.
 *   - No credential-format strings in any fixture.
 *
 * Spec: docs/roadmap.md MX.4
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { seedLockedGrades, assertA11y } from "./helpers";

// ---------------------------------------------------------------------------
// Block 1: Public pages (no auth required)
// ---------------------------------------------------------------------------

const PUBLIC_PAGES = [
  "/",
  "/product",
  "/how-it-works",
  "/about",
  "/pricing",
  "/ai",
  "/legal/terms",
  "/legal/privacy",
  "/legal/ferpa",
  "/legal/dpa",
  "/legal/ai-policy",
];

test.describe("MX.4 — Accessibility: public pages", () => {
  for (const path of PUBLIC_PAGES) {
    test(`${path} has no critical/serious WCAG 2.1 AA violations`, async ({ page }) => {
      await page.goto(path);
      // Wait for the main landmark to be visible before scanning
      await expect(page.locator("main").first()).toBeVisible({ timeout: 10_000 });
      await assertA11y(page);
    });
  }
});

// ---------------------------------------------------------------------------
// Block 2: Auth pages (no auth required)
// ---------------------------------------------------------------------------

test.describe("MX.4 — Accessibility: auth pages", () => {
  test("/login has no critical/serious WCAG 2.1 AA violations", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("main, [role='main'], body").first()).toBeVisible({
      timeout: 10_000,
    });
    await assertA11y(page);
  });

  test("/signup has no critical/serious WCAG 2.1 AA violations", async ({ page }) => {
    await page.goto("/signup");
    await expect(page.locator("main, [role='main'], body").first()).toBeVisible({
      timeout: 10_000,
    });
    await assertA11y(page);
  });
});

// ---------------------------------------------------------------------------
// Block 3: Grading interface (requires seeded data and auth)
// ---------------------------------------------------------------------------

test.describe("MX.4 — Accessibility: grading interface", () => {
  test.describe.configure({ mode: "serial" });

  const state: {
    email: string;
    password: string;
    assignmentId: string;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    email: "",
    password: "",
    assignmentId: "",
    context: null,
    page: null,
  };

  // seedLockedGrades triggers batch grading (up to 120 s) — allow time.
  test.setTimeout(180_000);

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(180_000);

    const fixture = await seedLockedGrades("mx4-a11y");
    state.email = fixture.email;
    state.password = fixture.password;
    state.assignmentId = fixture.assignmentId;

    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();

    // Log in via the UI form so the browser holds an httpOnly refresh_token
    await state.page.goto("/dashboard");
    await expect(state.page).toHaveURL(/\/login/, { timeout: 10_000 });
    await state.page.getByLabel("Email").fill(state.email);
    await state.page.getByLabel("Password").fill(state.password);
    await state.page.getByRole("button", { name: /sign in/i }).click();
    await expect(state.page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  // ── Test 1: Dashboard overview ────────────────────────────────────────────

  test("dashboard overview has no critical/serious violations", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    await page.goto("/dashboard");
    await expect(page.locator("main").first()).toBeVisible({ timeout: 15_000 });
    await assertA11y(page);
  });

  // ── Test 2: Assignment detail (review queue + export panel) ───────────────

  test("assignment detail page (review queue + export panel) has no critical/serious violations", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    await page.goto(`/dashboard/assignments/${state.assignmentId}`);
    // Wait for the essay list / export button to load
    await expect(
      page.getByRole("button", { name: /export options/i }),
    ).toBeVisible({ timeout: 15_000 });

    await assertA11y(page);
  });

  // ── Test 3: Export panel — menu accessible after opening ──────────────────

  test("export panel dropdown has no critical/serious violations when open", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    // Open the export menu
    const exportBtn = page.getByRole("button", { name: /export options/i });
    await exportBtn.click();
    await expect(page.getByRole("menu", { name: /export options/i })).toBeVisible({
      timeout: 5_000,
    });

    await assertA11y(page);

    // Close it again for subsequent tests
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).not.toBeVisible({ timeout: 3_000 });
  });

  // ── Test 4: Export panel — Escape returns focus to trigger ────────────────

  test("export panel closes on Escape and returns focus to trigger button", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    const exportBtn = page.getByRole("button", { name: /export options/i });
    await exportBtn.click();
    await expect(page.getByRole("menu", { name: /export options/i })).toBeVisible({
      timeout: 5_000,
    });

    // Escape must close the menu
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).not.toBeVisible({ timeout: 3_000 });

    // Focus must return to the trigger button
    await expect(exportBtn).toBeFocused({ timeout: 3_000 });
  });

  // ── Test 5: Essay review panel (EssayReviewPanel) ─────────────────────────

  test("essay review panel has no critical/serious violations", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    // Navigate to the review queue and click into the first essay
    await page.goto(`/dashboard/assignments/${state.assignmentId}/review`);
    const reviewQueue = page.getByRole("list", { name: /essays in this assignment/i });
    await expect(reviewQueue).toBeVisible({ timeout: 15_000 });
    const firstRow = reviewQueue.getByRole("listitem").first();
    await firstRow.click();

    // Wait for the grade review section to load
    await expect(
      page.getByRole("region", { name: /grade review/i }),
    ).toBeVisible({ timeout: 15_000 });

    await assertA11y(page);
  });

  // ── Test 6: Review queue — keyboard navigation (ArrowDown / Enter) ─────────

  test("review queue supports ArrowDown keyboard navigation to essays", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    await page.goto(`/dashboard/assignments/${state.assignmentId}/review`);

    // ReviewQueue rows are anchors with role="listitem" inside role="list"
    const reviewQueue = page.getByRole("list", { name: /essays in this assignment/i });
    await expect(reviewQueue).toBeVisible({ timeout: 15_000 });
    const queueItems = reviewQueue.getByRole("listitem");

    // We seeded two essays; ArrowDown on the first should move focus to second.
    const firstQueueItem = queueItems.nth(0);
    const secondQueueItem = queueItems.nth(1);

    // Focus the first essay row in the queue
    await firstQueueItem.focus();
    await expect(firstQueueItem).toBeFocused({ timeout: 5_000 });

    // ArrowDown should move focus to the next item
    await page.keyboard.press("ArrowDown");

    // Verify focus moved to the second essay row
    await expect(secondQueueItem).toBeFocused({ timeout: 3_000 });
  });

  // ── Test 7: Score inputs have accessible labels ───────────────────────────

  test("score inputs in essay review panel have accessible labels", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    // Navigate to the review queue and click into the first essay
    await page.goto(`/dashboard/assignments/${state.assignmentId}/review`);
    const reviewQueue = page.getByRole("list", { name: /essays in this assignment/i });
    await expect(reviewQueue).toBeVisible({ timeout: 15_000 });
    await reviewQueue.getByRole("listitem").first().click();
    await expect(
      page.getByRole("region", { name: /grade review/i }),
    ).toBeVisible({ timeout: 15_000 });

    // Every number input must have an accessible label
    const scoreInputs = page.getByRole("spinbutton");
    const count = await scoreInputs.count();
    expect(
      count,
      "Grade review panel loaded but did not render any score inputs",
    ).toBeGreaterThan(0);

    for (let i = 0; i < count; i++) {
      const input = scoreInputs.nth(i);
      const label = await input.getAttribute("aria-label");
      const id = await input.getAttribute("id");
      // Either aria-label or an associated <label for="id"> is required
      const hasAriaLabel = label !== null && label.length > 0;
      const hasLabelFor =
        id !== null &&
        (await page.locator(`label[for="${id}"]`).count()) > 0;
      expect(
        hasAriaLabel || hasLabelFor,
        `Score input at index ${i} (id="${id ?? "none"}") is missing an accessible label`,
      ).toBe(true);
    }
  });

  // ── Test 8: Status badges are announced correctly ─────────────────────────

  test("status badges in review queue have visible text or aria-label", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    await page.goto(`/dashboard/assignments/${state.assignmentId}/review`);

    // ReviewQueue rows are anchors with role="listitem"; status badges are
    // aria-hidden, so the row itself must carry a full accessible name.
    const reviewQueue = page.getByRole("list", { name: /essays in this assignment/i });
    await expect(reviewQueue).toBeVisible({ timeout: 15_000 });
    const reviewRows = reviewQueue.getByRole("listitem");

    const rowCount = await reviewRows.count();
    expect(
      rowCount,
      "Expected at least one review queue row to exist",
    ).toBeGreaterThan(0);

    for (let i = 0; i < rowCount; i++) {
      const row = reviewRows.nth(i);
      const label = await row.getAttribute("aria-label");
      expect(
        label,
        `Review queue row at index ${i} is missing an aria-label`,
      ).not.toBeNull();
      expect(
        label!.length,
        `Review queue row at index ${i} has an empty aria-label`,
      ).toBeGreaterThan(0);
    }
  });

  // ── Test 9: Locked grade — all inputs visually and functionally disabled ──

  test("locked grade in essay review panel has all controls disabled", async () => {
    if (!state.page) throw new Error("Page not initialised in beforeAll");
    const page = state.page;

    // Navigate to the review queue and click into the first essay
    await page.goto(`/dashboard/assignments/${state.assignmentId}/review`);
    const reviewQueue9 = page.getByRole("list", { name: /essays in this assignment/i });
    await expect(reviewQueue9).toBeVisible({ timeout: 15_000 });
    await reviewQueue9.getByRole("listitem").first().click();
    await expect(
      page.getByRole("region", { name: /grade review/i }),
    ).toBeVisible({ timeout: 15_000 });

    // All score inputs and textareas should be disabled for a locked grade
    const scoreInputs = page.getByRole("spinbutton");
    const inputCount = await scoreInputs.count();
    for (let i = 0; i < inputCount; i++) {
      await expect(scoreInputs.nth(i)).toBeDisabled();
    }

    const textareas = page.getByRole("textbox");
    const textareaCount = await textareas.count();
    for (let i = 0; i < textareaCount; i++) {
      await expect(textareas.nth(i)).toBeDisabled();
    }
  });
});
