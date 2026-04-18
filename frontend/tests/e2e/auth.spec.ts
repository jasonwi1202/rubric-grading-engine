/**
 * E2E: Authentication flows
 *
 * Covers the M2-delivered sign-up and email verification journeys, plus
 * middleware redirect behaviour for unauthenticated users.
 *
 * Journeys covered:
 *   1. Unauthenticated user hitting /dashboard is redirected to /login
 *   2. Unauthenticated user hitting /onboarding is redirected to /login
 *   3. /signup renders the registration form
 *   4. /signup form shows inline validation errors on empty submit
 *   5. Full sign-up → receive verification email → click link → account verified
 *   6. /auth/verify with an invalid token shows an error and a resend option
 *   7. /login page renders
 */

import { test, expect } from "@playwright/test";
import {
  testEmail,
  clearMailpit,
  waitForEmail,
  extractLinkFromEmail,
} from "./helpers";

test.describe("Middleware — unauthenticated redirects", () => {
  test("visiting /dashboard redirects to /login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("visiting /onboarding redirects to /login", async ({ page }) => {
    await page.goto("/onboarding");
    await expect(page).toHaveURL(/\/login/);
  });

  test("visiting /onboarding/class redirects to /login", async ({ page }) => {
    await page.goto("/onboarding/class");
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe("Sign-up page renders", () => {
  test("/signup renders the registration form", async ({ page }) => {
    await page.goto("/signup");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // All required form fields must be present
    await expect(page.getByLabel(/first name/i)).toBeVisible();
    await expect(page.getByLabel(/last name/i)).toBeVisible();
    await expect(page.getByLabel(/email/i).first()).toBeVisible();
    await expect(page.getByLabel(/password/i).first()).toBeVisible();
    await expect(
      page.getByRole("button", { name: /sign up|create|register/i }),
    ).toBeVisible();
  });

  test("/login page renders", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByLabel(/email/i).first()).toBeVisible();
    await expect(page.getByLabel(/password/i).first()).toBeVisible();
  });
});

test.describe("Sign-up form validation", () => {
  test("shows inline errors when submitted empty", async ({ page }) => {
    await page.goto("/signup");
    await page.getByRole("button", { name: /sign up|create|register/i }).click();
    // React Hook Form + Zod should surface at least one error
    const errors = page.locator("[role='alert'], [aria-live='polite'], .text-red, [data-error]");
    await expect(errors.first()).toBeVisible({ timeout: 5_000 });
  });

  test("shows error for invalid email format", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel(/email/i).first().fill("not-an-email");
    await page.getByLabel(/password/i).first().fill("ValidPass1!");
    await page.getByRole("button", { name: /sign up|create|register/i }).click();
    await expect(
      page.getByText(/valid email|invalid email/i).first(),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("shows error for short password", async ({ page }) => {
    await page.goto("/signup");
    await page.getByLabel(/email/i).first().fill("test@example.com");
    await page.getByLabel(/password/i).first().fill("short");
    await page.getByRole("button", { name: /sign up|create|register/i }).click();
    await expect(
      page.getByText(/password.*8|at least 8/i).first(),
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Full sign-up → email verification flow", () => {
  // This test requires the full Docker Compose stack including Mailpit.
  // It is the primary regression test for M2.8.
  test("teacher can sign up, receive verification email, and verify account", async ({
    page,
  }) => {
    const email = testEmail("verify");
    await clearMailpit();

    // --- Step 1: Fill and submit the sign-up form ---
    await page.goto("/signup");
    await page.getByLabel(/first name/i).fill("E2E");
    await page.getByLabel(/last name/i).fill("Teacher");
    await page.getByLabel(/email/i).first().fill(email);
    await page.getByLabel(/password/i).first().fill("TestPass123!");
    const schoolField = page.getByLabel(/school/i).first();
    if (await schoolField.isVisible()) {
      await schoolField.fill("E2E Test School");
    }
    await page.getByRole("button", { name: /sign up|create|register/i }).click();

    // --- Step 2: Should land on /signup/verify ---
    await expect(page).toHaveURL(/\/signup\/verify/, { timeout: 10_000 });
    await expect(page.getByText(/check your email/i)).toBeVisible();

    // --- Step 3: Poll Mailpit for the verification email ---
    const { body } = await waitForEmail(email, "verify", 15_000);
    const verifyUrl = extractLinkFromEmail(body);
    expect(verifyUrl).toContain("/auth/verify");

    // --- Step 4: Visit the verification link ---
    await page.goto(verifyUrl);
    // Should show success message and/or redirect to /login
    await expect(
      page
        .getByText(/verified|confirmed|success/i)
        .or(page.getByRole("heading", { name: /sign in|log in|welcome/i }))
        .first(),
    ).toBeVisible({ timeout: 10_000 });
  });
});

test.describe("/auth/verify — error states", () => {
  test("expired or invalid token shows error with resend option", async ({
    page,
  }) => {
    await page.goto("/auth/verify?token=invalid-token-abc123");
    await expect(
      page.getByText(/invalid|expired|not valid/i).first(),
    ).toBeVisible({ timeout: 10_000 });
    // Should offer a way to resend or go back
    const resend = page.getByRole("link", { name: /resend|try again|back/i });
    await expect(resend).toBeVisible();
  });
});
