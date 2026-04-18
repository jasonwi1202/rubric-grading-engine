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

import { test, expect } from "@playwright/test";

const STUB = "Not yet implemented — requires M3 APIs";

// ---------------------------------------------------------------------------
// Journey 1: Teacher login → create class → add students → create rubric → create assignment
// ---------------------------------------------------------------------------
test.describe("Journey 1 — Setup: login → class → students → rubric → assignment", () => {
  test.skip(true, STUB);

  test("teacher logs in successfully", async ({ page }) => {
    // TODO: fill once POST /api/v1/auth/login exists
    void page;
    expect(true).toBe(true);
  });

  test("teacher creates a class", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("teacher adds students to the class", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("teacher creates a rubric with criteria", async ({ page }) => {
    void page;
    expect(true).toBe(true);
  });

  test("teacher creates an assignment and attaches the rubric", async ({
    page,
  }) => {
    void page;
    expect(true).toBe(true);
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
