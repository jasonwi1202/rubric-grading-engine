/**
 * E2E stubs — Rubric Builder UI journeys (M3.3)
 *
 * These stubs establish the test structure for the rubric builder routes added
 * in M3.3 (#81).  All tests are skipped until the backend rubric endpoints
 * land in M3 so that CI continues to pass.
 *
 * To implement a journey, replace `test.skip(true, ...)` with the real test
 * body and remove the skip condition once the required backend APIs exist.
 *
 * Required APIs:
 *   - POST /api/v1/rubrics        (createRubric)
 *   - GET  /api/v1/rubrics/:id    (getRubric — for edit page hydration)
 *   - PATCH /api/v1/rubrics/:id   (updateRubric)
 *
 * Middleware:
 *   - Unauthenticated → /login?next=<currentPath>  (existing auth middleware)
 */

import { test, expect } from "@playwright/test";

const STUB = "Not yet implemented — requires M3 rubric CRUD APIs";

// ---------------------------------------------------------------------------
// Unauthenticated access — middleware redirects
// ---------------------------------------------------------------------------
test.describe("Rubric Builder — unauthenticated redirects", () => {
  test("visiting /dashboard/rubrics/new redirects to /login", async ({
    page,
  }) => {
    await page.goto("/dashboard/rubrics/new");
    await expect(page).toHaveURL(/\/login/);
  });

  test("visiting /dashboard/rubrics/:id/edit redirects to /login", async ({
    page,
  }) => {
    await page.goto("/dashboard/rubrics/test-rubric-id/edit");
    await expect(page).toHaveURL(/\/login/);
  });
});

// ---------------------------------------------------------------------------
// Create rubric journey
// ---------------------------------------------------------------------------
test.describe("Rubric Builder — create rubric", () => {
  test.skip(true, STUB);

  test("create page renders the rubric builder form", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("submitting a valid rubric saves it and redirects to the rubric list", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("weight-sum indicator turns green when criteria weights total 100%", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("submitting with weights != 100% shows a validation error", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Edit rubric journey
// ---------------------------------------------------------------------------
test.describe("Rubric Builder — edit rubric", () => {
  test.skip(true, STUB);

  test("edit page loads and hydrates the form with existing rubric data", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("updating a criterion name and saving succeeds", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("403 on edit page for rubric owned by another teacher redirects to dashboard", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });
});
