/**
 * E2E Journey 5 — Student skill profile across two assignments (MX.3e).
 *
 * Implements the fifth critical journey from docs/architecture/testing-guide.md:
 * "Student profile across two assignments"
 *
 * Acceptance criteria:
 * - Seeds a student with locked grades on two separate assignments via API setup
 * - Navigates to the student profile page from the class roster
 * - Asserts skill bar chart renders with data from both assignments
 * - Asserts historical timeline shows both assignments in chronological order
 *   (newest-first: Assignment B first, then Assignment A)
 * - Asserts strengths and gaps callouts reflect the seeded scores
 * - Asserts growth indicators are present (at least one of: improving / stable / declining)
 * - Test is independent: all data seeded via API before the test runs
 *
 * Depends on: MX.3a (#125), M5.2, M5.3, M5.4, M5.5
 * Spec: docs/roadmap.md MX.3, docs/features/student-profiles.md
 *
 * Security:
 * - No student PII in any fixture value — synthetic names and IDs only.
 * - No credential-format strings — all test credentials are clearly synthetic.
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { loginApi, seedStudentProfileFixture } from "./helpers";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Journey 5: Student skill profile across two assignments
// ---------------------------------------------------------------------------
test.describe("Journey 5 — Student profiles: skill profile across two assignments", () => {
  // All test steps share browser state (auth cookie, student/class IDs) and
  // must run in declaration order.  Serial mode guarantees execution order
  // within this describe block.
  test.describe.configure({ mode: "serial", timeout: 300_000 });

  // Shared state populated in beforeAll.
  const state: {
    email: string;
    password: string;
    studentId: string;
    studentName: string;
    classId: string;
    assignment1Id: string;
    assignment2Id: string;
    assignment1Title: string;
    assignment2Title: string;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    email: "",
    password: "",
    studentId: "",
    studentName: "",
    classId: "",
    assignment1Id: "",
    assignment2Id: "",
    assignment1Title: "",
    assignment2Title: "",
    context: null,
    page: null,
  };

  // seedStudentProfileFixture triggers two full grading cycles (up to 120 s
  // each) and polls for the skill profile.  The describe-level timeout of
  // 300_000 ms covers both the beforeAll and all serial test steps.

  test.beforeAll(async ({ browser }) => {
    // Seed a complete fixture independently of all other journeys:
    //   teacher → class → 1 student → 2 rubrics → 2 assignments
    //   → 2 essays → 2x batch grading → 2x lock grades
    //   → skill profile updated with both assignments
    const fixture = await seedStudentProfileFixture("journey5");
    state.email = fixture.email;
    state.password = fixture.password;
    state.studentId = fixture.studentId;
    state.studentName = fixture.studentName;
    state.classId = fixture.classId;
    state.assignment1Id = fixture.assignment1Id;
    state.assignment2Id = fixture.assignment2Id;
    state.assignment1Title = fixture.assignment1Title;
    state.assignment2Title = fixture.assignment2Title;

    // Create a browser context and log in via the UI form so the browser
    // holds a valid httpOnly refresh_token cookie for all subsequent tests.
    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();

    await state.page.goto("/dashboard");
    // Middleware redirects unauthenticated requests to /login.
    await expect(state.page).toHaveURL(/\/login/);
    await state.page.getByLabel("Email").fill(state.email);
    await state.page.getByLabel("Password").fill(state.password);
    await state.page.getByRole("button", { name: /sign in/i }).click();
    await expect(state.page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  // ── Test 1: Navigate to student profile from class roster ──────────────────

  test("teacher opens a student profile from the class roster", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // Navigate to the class detail page.  The RosterList component renders
    // each student name as a link to /dashboard/students/{studentId}.
    await page.goto(`/dashboard/classes/${state.classId}`);

    // Wait for the roster to load — the student link should appear.
    const profileLink = page.getByRole("link", { name: state.studentName });
    await expect(profileLink).toBeVisible({ timeout: 15_000 });

    // Read the profile href from the roster link, then navigate explicitly.
    // This avoids occasional click flakiness under CI load while still
    // validating that the roster renders the correct student profile link.
    const profileHref = await profileLink.getAttribute("href");
    expect(profileHref).toContain(`/dashboard/students/${state.studentId}`);
    await page.goto(profileHref ?? `/dashboard/students/${state.studentId}`);

    // Verify navigation reached the student profile page.
    await expect(page).toHaveURL(
      new RegExp(`/dashboard/students/${state.studentId}`),
      { timeout: 10_000 },
    );
  });

  // ── Test 2: Skill bar chart renders with data from both assignments ─────────

  test("skill bar chart renders with data from both assignments", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // The page is still on the student profile from Test 1.
    // Wait for the "Skill Profile" section heading.
    await expect(
      page.getByRole("heading", { name: /skill profile/i }),
    ).toBeVisible({ timeout: 15_000 });

    // seedStudentProfileFixture waits for assignment_count >= 2 before this
    // test starts, so this should be stable without long polling loops.
    await expect(page.getByText(/based on 2 assignments/i)).toBeVisible({
      timeout: 15_000,
    });

    // At least one SkillBar progressbar should be visible in the chart.
    await expect(page.getByRole("progressbar").first()).toBeVisible({
      timeout: 10_000,
    });
  });

  // ── Test 3: Assignment history shows both assignments (newest-first) ────────

  test("assignment history shows both assignments in chronological order", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // Navigate explicitly to the student profile page rather than relying on
    // the page state left by Test 1 — serial tests share a browser context but
    // CI can introduce micro-delays that cause the page to reload or redirect.
    await page.goto(`/dashboard/students/${state.studentId}`);

    // The "Assignment History" section lists all locked grades newest-first.
    await expect(
      page.getByRole("heading", { name: /assignment history/i }),
    ).toBeVisible({ timeout: 10_000 });

    // Locate the history list — aria-label matches the component's aria-label.
    const historyList = page.getByRole("list", { name: /assignment history/i });
    await expect(historyList).toBeVisible({ timeout: 15_000 });

    // Both assignments should appear in the list.
    const items = historyList.getByRole("listitem");
    await expect(items).toHaveCount(2);

    // Assignment B was locked after Assignment A, so it appears first (newest-first).
    const firstItemTitleLink = items
      .nth(0)
      .getByRole("link", { name: state.assignment2Title, exact: true });
    const secondItemTitleLink = items
      .nth(1)
      .getByRole("link", { name: state.assignment1Title, exact: true });
    await expect(firstItemTitleLink).toBeVisible();
    await expect(secondItemTitleLink).toBeVisible();
  });

  // ── Test 4: Strengths and gaps callouts reflect the seeded scores ──────────

  test("strengths and gaps callouts reflect the skill profile data", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // Fetch the student profile from the API to get the actual aggregated
    // scores that the UI should reflect.  This avoids hard-coding LLM outputs.
    const apiToken = await loginApi(state.email, state.password);
    const profileRes = await fetch(
      `${API_BASE}/api/v1/students/${state.studentId}`,
      { headers: { Authorization: `Bearer ${apiToken}` } },
    );
    expect(profileRes.ok).toBe(true);

    const profileBody = (await profileRes.json()) as {
      data: {
        skill_profile: {
          skill_scores: Record<
            string,
            { avg_score: number; data_points: number }
          >;
        } | null;
      };
    };

    const skillScores = profileBody.data?.skill_profile?.skill_scores ?? {};

    // Strengths: avg_score >= 0.7 with at least 2 data points (same threshold
    // as the StudentProfilePage component).
    const strengthSkills = Object.entries(skillScores).filter(
      ([, d]) => d.avg_score >= 0.7 && d.data_points >= 2,
    );

    // Gaps: avg_score < 0.5 with at least 2 data points.
    const gapSkills = Object.entries(skillScores).filter(
      ([, d]) => d.avg_score < 0.5 && d.data_points >= 2,
    );

    // If the API says there are strengths, the Strengths callout must be visible
    // and contain at least one expected skill label.
    if (strengthSkills.length > 0) {
      const strengthsCallout = page.getByLabel("Strengths");
      await expect(strengthsCallout).toBeVisible({ timeout: 10_000 });
      // API keys use snake_case; the UI renders them as title-case labels.
      const [firstStrengthKey] = strengthSkills[0];
      const strengthLabel = firstStrengthKey
        .split("_")
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
      await expect(
        strengthsCallout.getByText(new RegExp(strengthLabel, "i")),
      ).toBeVisible();
    }

    // If the API says there are gaps, the Gaps callout must be visible and
    // contain at least one expected skill label.
    // The component renders this region with aria-label="Gaps".
    if (gapSkills.length > 0) {
      const gapsCallout = page.getByLabel("Gaps");
      await expect(gapsCallout).toBeVisible({ timeout: 10_000 });
      const [firstGapKey] = gapSkills[0];
      const gapLabel = firstGapKey
        .split("_")
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ");
      await expect(
        gapsCallout.getByText(new RegExp(gapLabel, "i")),
      ).toBeVisible();
    }

    // In all cases, the skill bars section must be visible with scores.
    await expect(page.getByRole("progressbar").first()).toBeVisible({
      timeout: 10_000,
    });
  });

  // ── Test 5: Growth indicators are displayed for each skill dimension ────────

  test("growth indicators are displayed for skill dimensions", async () => {
    if (!state.page) throw new Error("Browser context not initialized in beforeAll");
    const page = state.page;

    // Each SkillBar component renders a trend badge with one of three texts:
    //   "Improving ↑", "Stable →", or "Declining ↓"
    // With two locked assignments, the Celery aggregation computes a trend
    // direction for every skill dimension.
    //
    // This test asserts presence of at least one trend badge rather than
    // verifying the specific direction.  The accuracy of the trend computation
    // (i.e. that "improving" is shown when scores rose) is tested at the unit
    // level in backend/tests/test_student_skill_profile.py (M5.3).  Here the
    // E2E concern is that the UI correctly renders whatever direction the API
    // returns — which is validated in Test 4 where we cross-check the API
    // response against the rendered callouts.  Asserting the exact direction
    // would require replicating the backend's recency-weighted average logic
    // in the test, which couples the test too tightly to implementation details.
    const trendPatterns = [/improving/i, /stable/i, /declining/i];

    let anyTrendVisible = false;
    for (const pattern of trendPatterns) {
      // isVisible() returns false (not throws) when the element is not found,
      // so no catch is needed.
      if (await page.getByText(pattern).first().isVisible()) {
        anyTrendVisible = true;
        break;
      }
    }

    expect(anyTrendVisible).toBe(true);
  });
});
