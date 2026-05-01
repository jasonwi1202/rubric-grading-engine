/**
 * E2E Journey 6 — Auto-grouping and Worklist (MX.6b).
 *
 * Covers the auto-grouping and worklist teacher journeys end-to-end against
 * the real Docker Compose stack.  No MSW — all requests hit the actual backend.
 *
 * Journey flow:
 *   1. Fixture seeds three students, two grading cycles (two assignments), and
 *      locks all grades so the auto-grouping Celery task fires.
 *   2. Teacher navigates to the class Groups tab and sees skill-gap groups with
 *      labels and student counts.
 *   3. Teacher expands a group to view its members.
 *   4. Teacher removes a student from the group (manual adjustment).
 *   5. Teacher adds the student back to the group (manual adjustment).
 *   6. Teacher navigates to the Dashboard worklist and sees urgency indicators.
 *   7. Teacher snoozes a worklist item — item disappears from list.
 *   8. Teacher marks a worklist item as done — item disappears.
 *   9. Teacher dismisses a worklist item — item disappears.
 *
 * Acceptance criteria (from issue MX.6b):
 * - Journey covers: grades lock, auto-grouping task runs, teacher views groups,
 *   teacher views worklist, marks item done.
 * - Test verifies group list renders with expected skill-gap labels and student counts.
 * - Test verifies worklist urgency indicators and snooze/dismiss interactions.
 * - Manual group adjustment (add/remove student) is exercised.
 * - No assertions on exact student names or essay content.
 *
 * Depends on: M6-03 (#184), M6-06 (#187)
 *
 * Security:
 * - No student PII in any fixture value — synthetic names and IDs only.
 * - No credential-format strings — all test credentials are clearly synthetic.
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { clearMailpit, seedAutoGroupingFixture } from "./helpers";
import type { AutoGroupingFixture } from "./helpers";

// ---------------------------------------------------------------------------
// Journey 6: Auto-grouping and Worklist
// ---------------------------------------------------------------------------
test.describe("Journey 6 — Auto-grouping and Worklist", () => {
  // All steps share a single browser context (auth cookie, fixture IDs) and
  // must run in declaration order.
  test.describe.configure({ mode: "serial", timeout: 480_000 });

  // Shared state populated in beforeAll.
  const state: {
    fixture: AutoGroupingFixture | null;
    context: BrowserContext | null;
    page: Page | null;
    /** ID of the first group visible in the Groups tab, captured in test 2 and used in tests 3–4 to target the same card regardless of render order. */
    firstGroupId: string | null;
  } = {
    fixture: null,
    context: null,
    page: null,
    firstGroupId: null,
  };

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(480_000);
    await clearMailpit();

    // Seed the full fixture: two grading cycles, grades locked, groups and
    // worklist items confirmed present before returning.
    state.fixture = await seedAutoGroupingFixture("journey6");

    // Create a browser context and log in via the UI form.
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

  // ── Test 1: Groups tab renders groups ──────────────────────────────────────

  test("Groups tab renders skill-gap groups with labels and student counts", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    await page.goto(`/dashboard/classes/${state.fixture.classId}`);

    // Click the Groups tab.
    const groupsTab = page.getByRole("tab", { name: /groups/i });
    await expect(groupsTab).toBeVisible({ timeout: 15_000 });
    await groupsTab.click();

    // The Groups heading should be visible.
    await expect(
      page.getByRole("heading", { name: /skill-gap groups/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Wait until at least one group card is rendered (the auto-grouping task has
    // already been confirmed by seedAutoGroupingFixture, so groups exist).
    await expect
      .poll(
        async () => {
          const items = page.locator('[aria-label^="Skill group:"]');
          return await items.count();
        },
        { timeout: 30_000, intervals: [1000, 2000] },
      )
      .toBeGreaterThanOrEqual(1);

    // Every visible group card must show a label text and a student count badge.
    const groupCards = page.locator('[aria-label^="Skill group:"]');
    const count = await groupCards.count();
    expect(count).toBeGreaterThanOrEqual(1);

    for (let i = 0; i < count; i++) {
      const card = groupCards.nth(i);
      // The skill label is encoded in the card's aria-label ("Skill group: {label}").
      // Assert the aria-label carries a non-empty skill name — no CSS class dependency.
      const ariaLabel = await card.getAttribute("aria-label") ?? "";
      expect(ariaLabel).toMatch(/Skill group:\s+\S/);
      // Student count badge contains the word "student" or "students".
      await expect(
        card.getByText(/\d+\s+students?/),
      ).toBeVisible();
    }
  });

  // ── Test 2: Expand group to view members ───────────────────────────────────

  test("Teacher expands a group to see its student members", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // The page is still on the class detail with the Groups tab active.
    // Find the first group card and click its expand button.
    const firstCard = page.locator('[aria-label^="Skill group:"]').first();
    await expect(firstCard).toBeVisible({ timeout: 10_000 });

    const expandButton = firstCard.getByRole("button", { name: /expand group/i });
    await expandButton.click();

    // Wait for the expanded member list to appear.
    const memberList = firstCard.locator("ul[aria-label]");
    await expect(memberList).toBeVisible({ timeout: 10_000 });

    // At least one student should be listed (we seeded 3 students, all in the group).
    const memberItems = memberList.getByRole("listitem");
    await expect
      .poll(
        async () => await memberItems.count(),
        { timeout: 10_000 },
      )
      .toBeGreaterThanOrEqual(1);

    // Extract the group ID from the aria-controls attribute of the expand button
    // so subsequent tests can target the same group without relying on position.
    const controlsAttr = await expandButton.getAttribute("aria-controls");
    if (controlsAttr) {
      // aria-controls is "group-members-{groupId}"
      state.firstGroupId = controlsAttr.replace("group-members-", "");
    }
  });

  // ── Test 3: Remove a student from a group (manual adjustment) ──────────────

  test("Teacher removes a student from a group", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // The first group card should still be expanded from the previous test.
    // Use firstGroupId (captured in test 2) to locate the same card regardless
    // of render order; fall back to .first() if the ID wasn't captured.
    const firstCard = state.firstGroupId
      ? page
          .locator('[aria-label^="Skill group:"]')
          .filter({
            has: page.locator(
              `[aria-controls="group-members-${state.firstGroupId}"]`,
            ),
          })
      : page.locator('[aria-label^="Skill group:"]').first();
    const memberList = firstCard.locator("ul[aria-label]");

    // Get initial member count.
    const initialCount = await memberList.getByRole("listitem").count();
    expect(initialCount).toBeGreaterThanOrEqual(1);

    // Click the Remove button on the first listed student.
    const firstRemoveButton = memberList
      .getByRole("button", { name: /remove/i })
      .first();
    await expect(firstRemoveButton).toBeVisible({ timeout: 5_000 });

    // Verify the aria-label is present ("Remove {student_name} from group").
    // We do NOT assert on the name itself, only that the label exists.
    const removeLabel = await firstRemoveButton.getAttribute("aria-label");
    expect(removeLabel).toBeTruthy();

    // Click Remove and wait for the save to complete.
    await firstRemoveButton.click();

    // The "Saving…" live region appears briefly while the PATCH is in-flight.
    // We don't assert on it since it's transient; instead poll for the count change.
    await expect
      .poll(
        async () => {
          // Count may be 0 when all students are removed.
          return await memberList.getByRole("listitem").count();
        },
        { timeout: 15_000, intervals: [500, 1000] },
      )
      .toBeLessThan(initialCount);
  });

  // ── Test 4: Add a student back to the group (manual adjustment) ────────────

  test("Teacher adds a student back to a group", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    // Target the same group card as tests 2 & 3.
    const firstCard = state.firstGroupId
      ? page
          .locator('[aria-label^="Skill group:"]')
          .filter({
            has: page.locator(
              `[aria-controls="group-members-${state.firstGroupId}"]`,
            ),
          })
      : page.locator('[aria-label^="Skill group:"]').first();
    const memberList = firstCard.locator("ul[aria-label]");

    const countBefore = await memberList.getByRole("listitem").count();

    // The "Add a student…" select appears when there are addable students.
    const addSelect = firstCard.locator("select[id^='add-student-']");
    await expect(addSelect).toBeVisible({ timeout: 10_000 });

    // Select any option (the first non-placeholder option).
    const options = addSelect.locator("option");
    const optionCount = await options.count();
    // Options[0] is the disabled placeholder; options[1] onwards are real students.
    expect(optionCount).toBeGreaterThan(1);

    const firstOption = options.nth(1);
    const optionValue = await firstOption.getAttribute("value");
    expect(optionValue).toBeTruthy();

    await addSelect.selectOption(optionValue!);

    // Wait for the member list to grow by one.
    await expect
      .poll(
        async () => await memberList.getByRole("listitem").count(),
        { timeout: 15_000, intervals: [500, 1000] },
      )
      .toBeGreaterThan(countBefore);
  });

  // ── Test 5: Worklist renders with urgency indicators ───────────────────────

  test("Worklist renders with urgency indicators for each item", async () => {
    if (!state.page) throw new Error("State not initialized");
    const page = state.page;

    await page.goto("/dashboard");

    // The dashboard renders the WorklistPanel.
    await expect(
      page.getByRole("heading", { name: /your worklist/i }),
    ).toBeVisible({ timeout: 15_000 });

    // Wait for the worklist to load (loading skeleton disappears).
    await expect(
      page.locator('[aria-label="Worklist items"]'),
    ).toBeVisible({ timeout: 30_000 });

    // Assert at least one item is present.
    const itemCards = page.locator('[aria-label="Worklist items"] li');
    const itemCount = await itemCards.count();
    expect(itemCount).toBeGreaterThanOrEqual(1);

    // Each item card has an urgency indicator dot (a colored circular element).
    // The dot is a <span class="block h-3 w-3 rounded-full ..."> inside the card.
    for (let i = 0; i < Math.min(itemCount, 3); i++) {
      const card = itemCards.nth(i);
      // Urgency badge is present: contains "Low", "Medium", "High", or "Critical".
      await expect(
        card.getByText(/\b(Low|Medium|High|Critical)\b/),
      ).toBeVisible();
      // Trigger reason is shown: one of the four trigger type labels.
      await expect(
        card.getByText(
          /Persistent Skill Gap|Score Regression|No Improvement After Feedback|High Inconsistency/,
        ),
      ).toBeVisible();
      // Action controls are present.
      await expect(
        card.getByRole("button", { name: /mark done/i }),
      ).toBeVisible();
      await expect(
        card.getByRole("button", { name: /snooze item/i }),
      ).toBeVisible();
      await expect(
        card.getByRole("button", { name: /dismiss item/i }),
      ).toBeVisible();
    }
  });

  // ── Test 6: Snooze a worklist item ─────────────────────────────────────────

  test("Teacher snoozes a worklist item and it disappears", async () => {
    if (!state.page) throw new Error("State not initialized");
    const page = state.page;

    const itemList = page.locator('[aria-label="Worklist items"]');
    const itemCards = itemList.locator("li");
    const countBefore = await itemCards.count();

    if (countBefore === 0) {
      test.skip(true, "No active worklist items — skipping snooze test");
      return;
    }

    // Snooze the first item.
    const firstCard = itemCards.first();
    const snoozeButton = firstCard.getByRole("button", { name: /snooze item/i });
    await expect(snoozeButton).toBeEnabled({ timeout: 5_000 });
    await snoozeButton.click();

    // The backend excludes snoozed items from the worklist response, so the
    // snoozed item should disappear from the list after the React Query refetch.
    await expect
      .poll(
        async () => await itemCards.count(),
        { timeout: 20_000, intervals: [500, 1000] },
      )
      .toBeLessThan(countBefore);
  });

  // ── Test 7: Mark a worklist item as done ───────────────────────────────────

  test("Teacher marks a worklist item as done and it disappears", async () => {
    if (!state.page) throw new Error("State not initialized");
    const page = state.page;

    const itemList = page.locator('[aria-label="Worklist items"]');
    const itemCards = itemList.locator("li");
    const countBefore = await itemCards.count();

    if (countBefore === 0) {
      test.skip(true, "No active worklist items — skipping mark-done test");
      return;
    }

    // Click Done on the first item.
    const firstCard = itemCards.first();
    const doneButton = firstCard.getByRole("button", { name: /mark done/i });
    await expect(doneButton).toBeEnabled({ timeout: 5_000 });
    await doneButton.click();

    // The worklist refetches after the mutation; the completed item is excluded
    // from the response, so the list should shrink.
    await expect
      .poll(
        async () => await itemCards.count(),
        { timeout: 20_000, intervals: [500, 1000] },
      )
      .toBeLessThan(countBefore);
  });

  // ── Test 8: Dismiss a worklist item ────────────────────────────────────────

  test("Teacher dismisses a worklist item and it disappears", async () => {
    if (!state.page) throw new Error("State not initialized");
    const page = state.page;

    const itemList = page.locator('[aria-label="Worklist items"]');
    const itemCards = itemList.locator("li");
    const countBefore = await itemCards.count();

    if (countBefore === 0) {
      test.skip(true, "No remaining worklist items — skipping dismiss test");
      return;
    }

    // Dismiss the first remaining active item.
    const firstCard = itemCards.first();
    const dismissButton = firstCard.getByRole("button", { name: /dismiss item/i });
    await expect(dismissButton).toBeEnabled({ timeout: 5_000 });
    await dismissButton.click();

    // The dismissed item should disappear from the list.
    await expect
      .poll(
        async () => await itemCards.count(),
        { timeout: 20_000, intervals: [500, 1000] },
      )
      .toBeLessThan(countBefore);
  });
});
