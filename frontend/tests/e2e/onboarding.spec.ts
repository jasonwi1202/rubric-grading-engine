/**
 * E2E: Onboarding wizard
 *
 * These tests require an authenticated teacher account.  A helper creates a
 * verified account and logs in before each test.  Login is implemented by
 * calling the backend auth API directly (not through the UI) to keep the
 * tests focused on onboarding behaviour, not re-testing the sign-up flow.
 *
 * Journeys covered:
 *   1. Unauthenticated user is redirected from /onboarding to /login (covered in auth.spec.ts)
 *   2. POST-login: wizard renders at /onboarding with correct step 1
 *   3. Teacher can skip step 1 (create class)
 *   4. Teacher can complete step 1 and advance to step 2 (build rubric)
 *   5. Teacher can skip step 2 and reach /onboarding/done
 *   6. /onboarding/done has a "Go to Dashboard" link
 *
 * NOTE: These tests depend on `POST /api/v1/auth/signup` + `GET /api/v1/auth/verify-email`
 * + `POST /api/v1/auth/login` being implemented.  The login endpoint is part of
 * M3.  Until then these tests are skipped via the `SKIP_AUTH_TESTS` env var.
 *
 * To run when auth is available:
 *   SKIP_AUTH_TESTS=false npx playwright test tests/e2e/onboarding.spec.ts
 */

import { test, expect, Page } from "@playwright/test";
import { testEmail, clearMailpit, waitForEmail, extractLinkFromEmail } from "./helpers";

const SKIP = process.env.SKIP_AUTH_TESTS !== "false";
const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

/** Create a verified teacher account and return a logged-in page. */
async function loginAsNewTeacher(page: Page): Promise<{ email: string; password: string }> {
  const email = testEmail("onboard");
  const password = "OnboardPass1!";
  await clearMailpit();

  // Create account
  const signupRes = await fetch(`${API_BASE}/api/v1/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      first_name: "E2E",
      last_name: "Onboard",
      email,
      password,
      school_name: "E2E School",
    }),
  });
  if (!signupRes.ok) throw new Error(`Signup failed: ${signupRes.status}`);

  // Verify email
  const { body } = await waitForEmail(email, "verify", 15_000);
  const verifyUrl = extractLinkFromEmail(body);
  const token = new URL(verifyUrl).searchParams.get("token");
  await fetch(`${API_BASE}/api/v1/auth/verify-email?token=${token}`);

  // Log in via UI
  await page.goto("/login");
  await page.getByLabel(/email/i).first().fill(email);
  await page.getByLabel(/password/i).first().fill(password);
  await page.getByRole("button", { name: /sign in|log in/i }).click();
  await expect(page).toHaveURL(/\/onboarding|\/dashboard/, { timeout: 10_000 });

  return { email, password };
}

test.describe("Onboarding wizard", () => {
  test.skip(SKIP, "Skipped until POST /api/v1/auth/login is implemented (M3). Set SKIP_AUTH_TESTS=false to run.");

  test("wizard renders step 1 after first login", async ({ page }) => {
    await loginAsNewTeacher(page);
    await page.goto("/onboarding");
    await expect(page.getByText(/step 1|create.*class/i).first()).toBeVisible();
  });

  test("can skip step 1 and reach step 2", async ({ page }) => {
    await loginAsNewTeacher(page);
    await page.goto("/onboarding");
    const skip = page.getByRole("button", { name: /skip/i }).first();
    await expect(skip).toBeVisible();
    await skip.click();
    await expect(page).toHaveURL(/\/onboarding\/rubric/, { timeout: 5_000 });
  });

  test("can skip step 2 and reach /onboarding/done", async ({ page }) => {
    await loginAsNewTeacher(page);
    await page.goto("/onboarding/rubric");
    const skip = page.getByRole("button", { name: /skip/i }).first();
    await skip.click();
    await expect(page).toHaveURL(/\/onboarding\/done/, { timeout: 5_000 });
  });

  test("/onboarding/done has a Go to Dashboard link", async ({ page }) => {
    await loginAsNewTeacher(page);
    await page.goto("/onboarding/done");
    const cta = page.getByRole("link", { name: /dashboard/i });
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute("href", "/dashboard");
  });

  test("can complete step 1 by creating a class", async ({ page }) => {
    await loginAsNewTeacher(page);
    await page.goto("/onboarding/class");
    await page.getByLabel(/class name/i).fill("Period 1");
    const gradeField = page.getByLabel(/grade/i).first();
    if (await gradeField.isVisible()) await gradeField.fill("8");
    await page.getByRole("button", { name: /next|continue|create/i }).click();
    await expect(page).toHaveURL(/\/onboarding\/rubric|\/onboarding\/done/, { timeout: 10_000 });
  });
});
