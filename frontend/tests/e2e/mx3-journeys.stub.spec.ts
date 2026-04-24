/**
 * E2E stubs — MX.3 critical journeys (placeholder specs for M3+)
 *
 * These are the 5 journeys defined in docs/architecture/testing-guide.md and
 * docs/roadmap.md (MX.3).  They are stubbed here so that:
 *
 *   1. The test suite structure is established before M3 ships.
 *   2. Copilot and contributors know exactly where to add implementation.
 *   3. CI doesn't fail — all tests are skipped via test.skip().
 *
 * To implement a journey, replace `test.skip(true, ...)` with the real test
 * body and remove the skip condition once the required backend APIs exist.
 *
 * Required APIs per journey (all in M3+):
 *   Journey 1 — POST /auth/login, POST /classes, POST /students, POST /rubrics, POST /assignments
 *   Journey 2 — POST /essays/upload, GET /essays (auto-assign), POST /grading/batch, GET /grading/status
 *   Journey 3 — GET /grades, PATCH /grades/:id (override), PATCH /grades/:id (feedback), POST /grades/:id/lock
 *   Journey 4 — POST /exports/batch, GET /exports/:id (download ZIP)
 *   Journey 5 — GET /students/:id/profile, GET /students/:id/skill-history
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { clearMailpit, seedTeacher } from "./helpers";

const STUB = "Not yet implemented — requires M3 APIs";

// ---------------------------------------------------------------------------
// Journey 1: Teacher login → create class → add students → create rubric → create assignment
// ---------------------------------------------------------------------------
test.describe("Journey 1 — Setup: login → class → students → rubric → assignment", () => {
  // All five steps depend on shared state (class ID, rubric name, etc.) and
  // must run in order.  A single browser context is created in beforeAll so
  // the refresh_token cookie (httpOnly) persists across all five test steps.
  // Serial mode guarantees execution order within the describe block.
  test.describe.configure({ mode: "serial" });

  // Shared state populated in beforeAll / earlier tests
  const state: {
    email: string;
    password: string;
    classId: string;
    className: string;
    rubricName: string;
    assignmentTitle: string;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    email: "",
    password: "",
    classId: "",
    className: "",
    rubricName: "",
    assignmentTitle: "",
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    // Clear stale emails so waitForEmail() picks up the right message.
    await clearMailpit();

    // Seed a fresh, verified teacher account via the API.
    const creds = await seedTeacher("journey1");
    state.email = creds.email;
    state.password = creds.password;

    // Unique names keyed to the epoch so parallel CI shards don't collide.
    const ts = Date.now();
    state.className = `E2E Class ${ts}`;
    state.rubricName = `E2E Rubric ${ts}`;
    state.assignmentTitle = `E2E Assignment ${ts}`;

    // Create a single browser context + page shared by all five serial steps.
    // This keeps the refresh_token cookie (httpOnly) alive across test boundaries.
    state.context = await browser.newContext();
    state.page = await state.context.newPage();
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  // ── Test 1: Login ─────────────────────────────────────────────────────────

  test("teacher logs in successfully", async () => {
    const page = state.page!;
    // Navigating to a protected route causes the middleware to redirect to
    // /login?next=/dashboard, which the login form honours after submit.
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);

    await page.getByLabel("Email").fill(state.email);
    await page.getByLabel("Password").fill(state.password);
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  // ── Test 2: Create class ──────────────────────────────────────────────────

  test("teacher creates a class", async () => {
    const page = state.page!;
    await page.goto("/dashboard/classes/new");

    await page.getByLabel("Class name").fill(state.className);
    await page.getByLabel("Subject").fill("English Language Arts");
    await page.getByLabel("Grade level").selectOption("Grade 8");
    // Academic year has a sensible default; leave it as-is.

    await page.getByRole("button", { name: "Create class" }).click();

    // Form redirects to the new class detail page — extract the class ID.
    await expect(page).toHaveURL(/\/dashboard\/classes\/[^/]+$/, {
      timeout: 15_000,
    });
    const classIdMatch = page.url().match(/\/classes\/([^/]+)$/);
    state.classId = classIdMatch?.[1] ?? "";
    expect(state.classId).toBeTruthy();

    // Navigate to the class list and confirm the new class is visible.
    await page.goto("/dashboard/classes");
    await expect(page.getByText(state.className)).toBeVisible();
  });

  // ── Test 3: Add two students ──────────────────────────────────────────────

  test("teacher adds students to the class", async () => {
    const page = state.page!;
    await page.goto(`/dashboard/classes/${state.classId}`);

    // Wait for the roster section to render before interacting.
    const rosterRegion = page.getByRole("region", { name: /students/i });
    await rosterRegion.waitFor();

    // ── Add first student ──
    await rosterRegion.getByRole("button", { name: "Add student" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    await dialog.getByLabel(/full name/i).fill("Student Alpha");
    await dialog.getByRole("button", { name: "Add student" }).click();

    // Dialog should close; student appears in the roster table.
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Student Alpha")).toBeVisible();

    // ── Add second student ──
    await rosterRegion.getByRole("button", { name: "Add student" }).click();
    await expect(dialog).toBeVisible({ timeout: 5_000 });
    await dialog.getByLabel(/full name/i).fill("Student Beta");
    await dialog.getByRole("button", { name: "Add student" }).click();

    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Student Beta")).toBeVisible();
  });

  // ── Test 4: Create rubric ─────────────────────────────────────────────────

  test("teacher creates a rubric with criteria", async () => {
    const page = state.page!;
    await page.goto("/dashboard/rubrics/new");

    // Name the rubric
    await page.getByLabel("Rubric name").fill(state.rubricName);

    // The builder starts with 3 default criteria (DEFAULT_CRITERION_COUNT = 3
    // in RubricBuilderForm).  Remove the third so we have exactly two criteria,
    // satisfying the ≥ 2 acceptance criterion.  If that default ever changes
    // this selector must be updated to match.
    await page.getByRole("button", { name: "Remove criterion 3" }).click();

    // Fill criterion 1 — name + weight
    await page.getByLabel("Criterion 1 name").fill("Argument Quality");
    await page.getByLabel("Criterion 1 weight (%)").fill("50");

    // Fill criterion 2 — name + weight  (50 + 50 = 100% total)
    await page.getByLabel("Criterion 2 name").fill("Evidence Use");
    await page.getByLabel("Criterion 2 weight (%)").fill("50");

    await page.getByRole("button", { name: "Create rubric" }).click();

    // Successful save redirects back to the dashboard.
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  // ── Test 5: Create assignment ─────────────────────────────────────────────

  test("teacher creates an assignment and attaches the rubric", async () => {
    const page = state.page!;
    await page.goto(
      `/dashboard/classes/${state.classId}/assignments/new`,
    );

    // Fill the assignment title
    await page.getByLabel("Title").fill(state.assignmentTitle);

    // Wait for the rubric dropdown to load, then select our rubric.
    const rubricSelect = page.getByLabel("Rubric");
    await expect(rubricSelect).toContainText(state.rubricName, {
      timeout: 10_000,
    });
    const rubricOption = rubricSelect.locator("option", {
      hasText: state.rubricName,
    });
    const rubricValue = await rubricOption.getAttribute("value");
    if (!rubricValue) {
      throw new Error(
        `Rubric option for "${state.rubricName}" is missing a value attribute`,
      );
    }
    await rubricSelect.selectOption(rubricValue);

    await page.getByRole("button", { name: "Create assignment" }).click();

    // Redirects to the assignment detail page.
    await expect(page).toHaveURL(/\/dashboard\/assignments\//, {
      timeout: 15_000,
    });

    // Navigate to the class page and confirm the assignment is listed.
    await page.goto(`/dashboard/classes/${state.classId}`);
    await expect(page.getByText(state.assignmentTitle)).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Journey 2: Upload essays → review auto-assignments → trigger grading → watch progress
// ---------------------------------------------------------------------------
test.describe("Journey 2 — Grading: upload → auto-assign → batch grade → progress", () => {
  test.skip(true, STUB);

  test("teacher uploads essay files to an assignment", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("auto-assignment correctly matches essays to students", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("teacher triggers batch grading and sees progress bar", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("grading completes and review queue is populated", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Journey 3: Open review queue → override score → edit feedback → lock grade
// ---------------------------------------------------------------------------
test.describe("Journey 3 — Review: open queue → override → edit feedback → lock", () => {
  test.skip(true, STUB);

  test("teacher opens review queue and sees AI-generated grades", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("teacher overrides a criterion score and sees it saved", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("teacher edits feedback text and sees it saved", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("teacher locks a grade and controls become read-only", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Journey 4: Export batch as PDF ZIP → download
// ---------------------------------------------------------------------------
test.describe("Journey 4 — Export: batch PDF ZIP → download", () => {
  test.skip(true, STUB);

  test("teacher initiates a batch PDF export", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("export completes and download link is available", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("downloaded ZIP contains one PDF per student", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Journey 5: View student profile → see skill history across two assignments
// ---------------------------------------------------------------------------
test.describe("Journey 5 — Student profiles: profile → skill history", () => {
  test.skip(true, STUB);

  test("teacher opens a student profile from the class roster", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("student profile shows skill scores from the most recent assignment", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });

  test("skill history chart shows trend across two assignments", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
  });
});
