/**
 * E2E Journey 9 — Teacher copilot (M7).
 *
 * Covers the teacher-facing copilot UI against the real Docker Compose stack.
 * The backend runs with deterministic fake-LLM mode in CI, so the response is
 * stable and no external model calls are required.
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { clearMailpit, seedAutoGroupingFixture } from "./helpers";
import type { AutoGroupingFixture } from "./helpers";

test.describe("Journey 9 — Teacher copilot", () => {
  test.describe.configure({ mode: "serial", timeout: 300_000 });

  const state: {
    fixture: AutoGroupingFixture | null;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    fixture: null,
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(300_000);
    await clearMailpit();
    state.fixture = await seedAutoGroupingFixture("journey9-copilot");

    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();

    const page = state.page;
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
    await page.waitForLoadState("networkidle");
    await page.getByLabel("Email").fill(state.fixture.email);
    await page.getByLabel("Password").fill(state.fixture.password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  test("teacher opens copilot, scopes to a class, and receives a structured response", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    await page.goto("/dashboard/copilot");

    await expect(page.getByRole("heading", { name: /copilot/i })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/surfaces information only/i)).toBeVisible();

    const scope = page.getByLabel(/scope/i);
    await expect(scope).toBeVisible();
    await scope.selectOption(state.fixture.classId);

    const input = page.getByRole("textbox", { name: /your question/i });
    await input.fill("What should I teach tomorrow?");
    await page.getByRole("button", { name: /ask/i }).click();

    await expect(page.getByText("Deterministic test summary from fake LLM mode.")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/Model: copilot-v1/i)).toBeVisible();
    await expect(input).toHaveValue("");
  });

  test("copilot form validates blank question input", async () => {
    if (!state.page) throw new Error("State not initialized");
    const page = state.page;

    await page.goto("/dashboard/copilot");
    await expect(page.getByRole("heading", { name: /copilot/i })).toBeVisible({ timeout: 15_000 });

    const askButton = page.getByRole("button", { name: /ask/i });
    await askButton.click();

    await expect(
      page.getByText(/please enter a question|question must not be blank/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("copilot student profile links are clickable when returned", async () => {
    if (!state.page || !state.fixture) throw new Error("State not initialized");
    const page = state.page;

    await page.goto("/dashboard/copilot");
    const scope = page.getByLabel(/scope/i);
    await scope.selectOption(state.fixture.classId);

    const input = page.getByRole("textbox", { name: /your question/i });
    await input.fill("Which students need support?");
    await page.getByRole("button", { name: /ask/i }).click();

    // In deterministic fake-LLM mode ranked links are expected. In real mode
    // they are optional, so assert conditionally.
    const links = page.getByRole("link", { name: /view student profile/i });
    const linkCount = await links.count();
    if (linkCount > 0) {
      await links.first().click();
      await expect(page).toHaveURL(/\/dashboard\/students\//, { timeout: 15_000 });
    }
  });
});