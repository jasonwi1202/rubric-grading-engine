/**
 * E2E: Rubric Builder UI journeys (M3.3)
 *
 * Covers:
 * - Unauthenticated redirects for create/edit routes
 * - Create rubric form behavior (render, weight validation, save)
 * - Edit rubric flow (hydration, update, save)
 * - Cross-teacher access on edit route (403 -> dashboard redirect)
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { loginApi, seedRubric, seedTeacher } from "./helpers";

async function loginViaUi(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  await page.getByLabel(/email/i).first().fill(email);
  await page.getByLabel(/password/i).first().fill(password);
  await page.getByRole("button", { name: /sign in|log in/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
}

// ---------------------------------------------------------------------------
// Unauthenticated access - middleware redirects
// ---------------------------------------------------------------------------

test.describe("Rubric Builder - unauthenticated redirects", () => {
  test("visiting /dashboard/rubrics/new redirects to /login", async ({ page }) => {
    await page.goto("/dashboard/rubrics/new");
    await expect(page).toHaveURL(/\/login/);
  });

  test("visiting /dashboard/rubrics/:id/edit redirects to /login", async ({ page }) => {
    await page.goto("/dashboard/rubrics/test-rubric-id/edit");
    await expect(page).toHaveURL(/\/login/);
  });
});

// ---------------------------------------------------------------------------
// Create rubric journey
// ---------------------------------------------------------------------------

test.describe("Rubric Builder - create rubric", () => {
  test.describe.configure({ mode: "serial", timeout: 180_000 });

  const state: {
    email: string;
    password: string;
    rubricName: string;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    email: "",
    password: "",
    rubricName: "",
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    const creds = await seedTeacher("rubric-create");
    state.email = creds.email;
    state.password = creds.password;
    state.rubricName = `E2E Rubric Create ${Date.now()}`;

    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();
    await loginViaUi(state.page, state.email, state.password);
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  test("create page renders the rubric builder form", async () => {
    if (!state.page) throw new Error("Browser context not initialized");
    const page = state.page;

    await page.goto("/dashboard/rubrics/new");
    await expect(page.getByRole("heading", { name: /new rubric/i })).toBeVisible();
    await expect(page.getByLabel("Rubric name")).toBeVisible();
    await expect(page.locator('[data-testid="weight-sum-indicator"]')).toBeVisible();
    await expect(page.getByRole("button", { name: /create rubric/i })).toBeVisible();
  });

  test("weight-sum indicator turns valid when criteria weights total 100", async () => {
    if (!state.page) throw new Error("Browser context not initialized");
    const page = state.page;

    await page.goto("/dashboard/rubrics/new");
    await page.getByLabel("Rubric name").fill(`Weight Sum ${Date.now()}`);

    // Start from 2 criteria for deterministic weights.
    await page.getByRole("button", { name: "Remove criterion 3" }).click();

    await page.getByLabel("Criterion 1 name").fill("Argument Quality");
    await page.getByLabel("Criterion 1 weight (%)").fill("50");

    await page.getByLabel("Criterion 2 name").fill("Evidence Use");
    await page.getByLabel("Criterion 2 weight (%)").fill("50");

    const indicator = page.locator('[data-testid="weight-sum-indicator"]');
    await expect(indicator).toContainText(/100%/i);
    await expect(indicator).toContainText(/\u2713/);
  });

  test("submitting with weights not equal to 100 shows validation error", async () => {
    if (!state.page) throw new Error("Browser context not initialized");
    const page = state.page;

    await page.goto("/dashboard/rubrics/new");
    await page.getByLabel("Rubric name").fill(`Invalid Weights ${Date.now()}`);

    await page.getByRole("button", { name: "Remove criterion 3" }).click();

    await page.getByLabel("Criterion 1 name").fill("Argument Quality");
    await page.getByLabel("Criterion 1 weight (%)").fill("70");

    await page.getByLabel("Criterion 2 name").fill("Evidence Use");
    await page.getByLabel("Criterion 2 weight (%)").fill("20");

    await page.getByRole("button", { name: /create rubric/i }).click();

    await expect(
      page.getByText(/criterion weights must sum to 100/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("submitting a valid rubric saves and redirects to dashboard", async () => {
    if (!state.page) throw new Error("Browser context not initialized");
    const page = state.page;

    await page.goto("/dashboard/rubrics/new");
    await page.getByLabel("Rubric name").fill(state.rubricName);

    await page.getByRole("button", { name: "Remove criterion 3" }).click();

    await page.getByLabel("Criterion 1 name").fill("Argument Quality");
    await page.getByLabel("Criterion 1 weight (%)").fill("50");

    await page.getByLabel("Criterion 2 name").fill("Evidence Use");
    await page.getByLabel("Criterion 2 weight (%)").fill("50");

    const saveResponse = page.waitForResponse(
      (response) => {
        const pathname = new URL(response.url()).pathname;
        return (
          response.request().method() === "POST" &&
          pathname.endsWith("/api/v1/rubrics") &&
          response.ok()
        );
      },
      { timeout: 20_000 },
    );

    await page.getByRole("button", { name: /create rubric/i }).click();
    await saveResponse;

    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// Edit rubric journey
// ---------------------------------------------------------------------------

test.describe("Rubric Builder - edit rubric", () => {
  test.describe.configure({ mode: "serial", timeout: 180_000 });

  const state: {
    ownerEmail: string;
    ownerPassword: string;
    otherEmail: string;
    otherPassword: string;
    rubricId: string;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    ownerEmail: "",
    ownerPassword: "",
    otherEmail: "",
    otherPassword: "",
    rubricId: "",
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    const owner = await seedTeacher("rubric-owner");
    state.ownerEmail = owner.email;
    state.ownerPassword = owner.password;

    const ownerToken = await loginApi(owner.email, owner.password);
    state.rubricId = await seedRubric(ownerToken, `E2E Edit Rubric ${Date.now()}`);

    const other = await seedTeacher("rubric-other");
    state.otherEmail = other.email;
    state.otherPassword = other.password;

    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();
    await loginViaUi(state.page, state.ownerEmail, state.ownerPassword);
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  test("edit page loads and hydrates existing rubric data", async () => {
    if (!state.page) throw new Error("Browser context not initialized");
    const page = state.page;

    await page.goto(`/dashboard/rubrics/${state.rubricId}/edit`);

    await expect(page.getByRole("heading", { name: /edit rubric/i })).toBeVisible({
      timeout: 15_000,
    });

    await expect(page.getByLabel("Rubric name")).toHaveValue(/E2E Edit Rubric/i);
    await expect(page.getByLabel("Criterion 1 name")).toHaveValue("Argument Quality");
    await expect(page.getByLabel("Criterion 2 name")).toHaveValue("Evidence Use");
  });

  test("updating rubric name and saving succeeds", async () => {
    if (!state.page) throw new Error("Browser context not initialized");
    const page = state.page;

    await page.goto(`/dashboard/rubrics/${state.rubricId}/edit`);

    const updatedRubricName = `E2E Edit Rubric Updated ${Date.now()}`;
    await page.getByLabel("Rubric name").fill(updatedRubricName);

    const saveResponse = page.waitForResponse(
      (response) => {
        const pathname = new URL(response.url()).pathname;
        return (
          response.request().method() === "PATCH" &&
          pathname.endsWith(`/api/v1/rubrics/${state.rubricId}`) &&
          response.ok()
        );
      },
      { timeout: 20_000 },
    );

    await page.getByRole("button", { name: /save changes/i }).click();
    await saveResponse;

    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });

    // Re-open edit page and verify persisted value.
    await page.goto(`/dashboard/rubrics/${state.rubricId}/edit`);
    await expect(page.getByLabel("Rubric name")).toHaveValue(updatedRubricName);
  });

  test("cross-teacher edit route redirects to dashboard", async ({ browser }) => {
    const otherContext = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    const otherPage = await otherContext.newPage();

    await loginViaUi(otherPage, state.otherEmail, state.otherPassword);
    await otherPage.goto(`/dashboard/rubrics/${state.rubricId}/edit`);

    await expect(otherPage).toHaveURL(/\/dashboard$/, { timeout: 15_000 });

    await otherContext.close();
  });
});

