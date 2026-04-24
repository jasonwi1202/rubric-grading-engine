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
import {
  clearMailpit,
  loginApi,
  seedAssignment,
  seedClass,
  seedRubric,
  seedStudent,
  seedTeacher,
} from "./helpers";

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
    // Pass baseURL so that relative goto() calls (e.g. "/dashboard") resolve
    // correctly — browser.newContext() does not inherit use.baseURL from the
    // Playwright config automatically (that only applies to the built-in page fixture).
    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  // ── Test 1: Login ─────────────────────────────────────────────────────────

  test("teacher logs in successfully", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;
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
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;
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
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;
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
    // Re-query the dialog so the locator resolves against the newly mounted element.
    const dialog2 = page.getByRole("dialog");
    await expect(dialog2).toBeVisible({ timeout: 5_000 });
    await dialog2.getByLabel(/full name/i).fill("Student Beta");
    await dialog2.getByRole("button", { name: "Add student" }).click();

    await expect(dialog2).not.toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Student Beta")).toBeVisible();
  });

  // ── Test 4: Create rubric ─────────────────────────────────────────────────

  test("teacher creates a rubric with criteria", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;
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
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;
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
  // All four steps share state (assignment ID, class ID, etc.) and must run
  // in the order defined below.  A single browser context persists so the
  // auth cookie carries across navigations.
  test.describe.configure({ mode: "serial" });

  // ---------------------------------------------------------------------------
  // Student names are crafted so the auto-assignment algorithm (rapidfuzz
  // filename fuzzy-match, threshold 0.85) reliably assigns each essay to the
  // correct student.  The essay files are named "<StudentName>.txt" so the
  // filename stem exactly matches the enrolled student's full_name → 100 %
  // confidence, well above the 0.85 threshold.
  // ---------------------------------------------------------------------------
  const STUDENT_1 = "Alpha Writer";
  const STUDENT_2 = "Beta Writer";

  const state: {
    email: string;
    password: string;
    classId: string;
    assignmentId: string;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    email: "",
    password: "",
    classId: "",
    assignmentId: "",
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    // 1. Seed a fresh verified teacher account (independent of Journey 1).
    await clearMailpit();
    const creds = await seedTeacher("journey2");
    state.email = creds.email;
    state.password = creds.password;

    // 2. Exchange credentials for a JWT access token to seed backend data
    //    without going through the browser UI.
    const token = await loginApi(state.email, state.password);

    // 3. Seed the class → students → rubric → assignment hierarchy.
    //    Using a timestamp suffix prevents name collisions on shared backends.
    const ts = Date.now();
    state.classId = await seedClass(token, `J2 Class ${ts}`);
    await seedStudent(token, state.classId, STUDENT_1);
    await seedStudent(token, state.classId, STUDENT_2);
    const rubricId = await seedRubric(token, `J2 Rubric ${ts}`);
    // seedAssignment creates the assignment in "draft" then transitions it to
    // "open" so essays can be uploaded and grading can be triggered.
    state.assignmentId = await seedAssignment(
      token,
      state.classId,
      rubricId,
      `J2 Assignment ${ts}`,
    );

    // 4. Create a browser context and log in via the UI form so the browser
    //    holds a valid refresh_token httpOnly cookie for all subsequent tests.
    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();

    await state.page.goto("/dashboard");
    // The middleware redirects unauthenticated requests to /login.
    await expect(state.page).toHaveURL(/\/login/);
    await state.page.getByLabel("Email").fill(state.email);
    await state.page.getByLabel("Password").fill(state.password);
    await state.page.getByRole("button", { name: /sign in/i }).click();
    await expect(state.page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  // ── Test 1: Upload two essay files ────────────────────────────────────────

  test("teacher uploads essay files to an assignment", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // Navigate to the essay-input page for the seeded assignment.
    // classId is passed as a query param so the page can load the class roster
    // (used by AutoAssignmentReview for the student picker).
    await page.goto(
      `/dashboard/assignments/${state.assignmentId}/essays?classId=${state.classId}`,
    );

    // Open the upload dialog.
    await page.getByRole("button", { name: "Upload essays" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Upload two plain-text essay files.  The filenames are "<StudentName>.txt"
    // so the auto-assignment algorithm can match them to enrolled students
    // by filename fuzzy-matching (confidence approaches 1.0 for an exact stem
    // match).  The essay body begins with the student name so the header-text
    // signal also produces a high-confidence match.
    await page.locator('input[aria-label="Select essay files"]').setInputFiles([
      {
        name: `${STUDENT_1}.txt`,
        mimeType: "text/plain",
        buffer: Buffer.from(
          `${STUDENT_1}\n\n` +
            "This essay presents a clear and well-supported argument. " +
            "The author uses multiple pieces of textual evidence to defend the " +
            "central thesis and organises the discussion in a logical sequence. " +
            "The prose is concise and the vocabulary is appropriate for the grade level.",
        ),
      },
      {
        name: `${STUDENT_2}.txt`,
        mimeType: "text/plain",
        buffer: Buffer.from(
          `${STUDENT_2}\n\n` +
            "This essay demonstrates strong analytical skills and a clear point of " +
            "view. Each body paragraph begins with a topic sentence supported by " +
            "relevant quotations. The conclusion effectively synthesises the main " +
            "ideas and leaves the reader with a memorable final impression.",
        ),
      },
    ]);

    // Both filenames should appear in the selected-files list inside the dialog.
    await expect(dialog.getByText(`${STUDENT_1}.txt`)).toBeVisible({
      timeout: 5_000,
    });
    await expect(dialog.getByText(`${STUDENT_2}.txt`)).toBeVisible({
      timeout: 5_000,
    });

    // Trigger the upload.
    await dialog.getByRole("button", { name: /^upload$/i }).click();

    // The dialog closes once the server responds with 200.  Give the backend
    // a generous window — it processes MIME validation and S3 upload inline.
    await expect(dialog).not.toBeVisible({ timeout: 30_000 });
  });

  // ── Test 2: Auto-assignment review ────────────────────────────────────────

  test("auto-assignment correctly matches essays to students", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // After the upload dialog closes, the page re-fetches the essay list and
    // renders AutoAssignmentReview.  Wait for the review heading to appear.
    await expect(
      page.getByRole("heading", { name: /review auto-assignment/i }),
    ).toBeVisible({ timeout: 10_000 });

    // The summary line should report that both essays were matched.
    await expect(page.getByText(/2 of 2 essays? were matched automatically/i)).toBeVisible({
      timeout: 5_000,
    });

    // The "Auto-assigned" section lists essays whose student was determined
    // automatically.  Both essays should appear there.
    const autoAssignedTable = page.getByRole("table", {
      name: /auto-assigned essays/i,
    });
    await expect(autoAssignedTable).toBeVisible({ timeout: 5_000 });

    // If any essays ended up in "Needs assignment" (e.g. the mock environment
    // returned a low-confidence match) the teacher must assign them manually
    // before the "Proceed to grading" button becomes enabled.
    const needsAssignTable = page.getByRole("table", {
      name: /essays needing assignment/i,
    });
    if (await needsAssignTable.isVisible()) {
      // Assign every unresolved essay to any available student.
      const rows = needsAssignTable.getByRole("row").filter({
        has: page.getByRole("combobox"),
      });
      const rowCount = await rows.count();
      for (let i = 0; i < rowCount; i++) {
        const row = rows.nth(i);
        const select = row.getByRole("combobox");
        // Choose the first real option (index 0 is the placeholder "— Select student —").
        await select.selectOption({ index: 1 });
        await row.getByRole("button", { name: /save/i }).click();
        // Wait for the save button to disappear (essay marked as assigned server-side).
        await expect(row.getByRole("button", { name: /save/i })).not.toBeVisible({
          timeout: 10_000,
        });
      }
    }

    // The "Proceed to grading" button becomes enabled only when every essay
    // has a student assigned.  This confirms all auto-assignments are resolved.
    await expect(
      page.getByRole("button", { name: /proceed to grading/i }),
    ).toBeEnabled({ timeout: 10_000 });

    // Verify the "All essays are assigned." status message is visible.
    await expect(page.getByText(/all essays are assigned/i)).toBeVisible({
      timeout: 5_000,
    });
  });

  // ── Test 3: Trigger batch grading and assert progress bar ─────────────────

  test("teacher triggers batch grading and sees progress bar", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // Navigate to the assignment overview page where BatchGradingPanel lives.
    // The essays page "Proceed to grading" button targets a /grade sub-route
    // that is not yet implemented; we navigate directly to the overview instead.
    await page.goto(`/dashboard/assignments/${state.assignmentId}`);

    // The "Grade now" button is only shown when canGrade is true (assignment
    // status is "open" or "grading") and the grading status is idle or terminal.
    // Our seeded assignment is in "open" status and no grading has started,
    // so the button must be visible.
    await expect(
      page.getByRole("button", { name: "Grade now" }),
    ).toBeVisible({ timeout: 15_000 });

    // Trigger batch grading.
    await page.getByRole("button", { name: "Grade now" }).click();

    // The BatchGradingPanel renders a <progress> element (aria-label contains
    // "Grading progress") once the grading-status endpoint returns a
    // non-idle status.  The progress bar is wrapped in a container whose
    // aria-label matches the pattern below.
    await expect(
      page.locator('[aria-label*="Grading progress"]').first(),
    ).toBeVisible({ timeout: 20_000 });
  });

  // ── Test 4: Grading completes without failures ─────────────────────────────

  test("grading completes and no essays show failed status", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // The BatchGradingPanel polls the grading-status endpoint every 3 s and
    // renders a completion message once the batch reaches a terminal state.
    // Give a generous timeout to allow Celery to process both essays.
    await expect(page.getByText(/grading complete/i)).toBeVisible({
      timeout: 120_000,
    });

    // The completion message should report that at least one essay was graded.
    await expect(
      page.getByText(/essay[s]? graded successfully/i),
    ).toBeVisible({ timeout: 5_000 });

    // There must be no "Failed" status badges in the per-essay table.  Each
    // failed essay would show a badge with the exact text "Failed".
    const failedBadges = page.getByRole("cell").filter({
      has: page.getByText("Failed"),
    });
    await expect(failedBadges).toHaveCount(0);
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
