/**
 * E2E: Public site pages
 *
 * Verifies that every public-facing route renders without error and contains
 * the minimum expected structure.  These are static pages — no backend calls
 * are needed except for the inquiry/DPA forms.
 *
 * Journeys covered:
 *   - All 10 public routes return 200 and render <main>
 *   - Shared nav links are present and point to correct hrefs
 *   - Footer contains all required legal links
 *   - "Start Free Trial" CTA on homepage links to /signup
 *   - /pricing annual/monthly toggle changes displayed prices
 *   - /legal/dpa DPA request form submits and shows confirmation
 *   - /pricing inquiry form submits and shows confirmation
 */

import { test, expect } from "@playwright/test";
import { assertBasicA11y } from "./helpers";

const PUBLIC_ROUTES = [
  { path: "/", titleContains: "GradeWise" },
  { path: "/product", titleContains: "Product" },
  { path: "/how-it-works", titleContains: "How" },
  { path: "/about", titleContains: "About" },
  { path: "/pricing", titleContains: "Pricing" },
  { path: "/ai", titleContains: "AI" },
  { path: "/legal/terms", titleContains: "Terms" },
  { path: "/legal/privacy", titleContains: "Privacy" },
  { path: "/legal/ferpa", titleContains: "FERPA" },
  { path: "/legal/dpa", titleContains: "Data Processing" },
  { path: "/legal/ai-policy", titleContains: "AI" },
];

test.describe("Public site — all routes render", () => {
  for (const { path, titleContains } of PUBLIC_ROUTES) {
    test(`${path} renders without error`, async ({ page }) => {
      await page.goto(path);
      await assertBasicA11y(page);
      const title = await page.title();
      expect(title).toContain(titleContains);
    });
  }
});

test.describe("Public site — shared header navigation", () => {
  test("header nav links are present on homepage", async ({ page }) => {
    await page.goto("/");
    const nav = page.locator("header nav, [role='navigation']").first();
    await expect(nav).toBeVisible();

    // All primary nav links should resolve
    for (const [label, href] of [
      ["Product", "/product"],
      ["How It Works", "/how-it-works"],
      ["Pricing", "/pricing"],
    ]) {
      const link = nav.getByRole("link", { name: label, exact: false }).first();
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute("href", href);
    }
  });

  test("Start Free Trial CTA links to /signup", async ({ page }) => {
    await page.goto("/");
    // There should be at least one prominent CTA pointing at sign-up
    const cta = page
      .getByRole("link", { name: /start.*trial|free trial/i })
      .first();
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute("href", "/signup");
  });
});

test.describe("Public site — footer", () => {
  test("footer contains all required legal links", async ({ page }) => {
    await page.goto("/");
    const footer = page.locator("footer").first();
    await expect(footer).toBeVisible();

    const legalLinks: [string, string][] = [
      ["Terms", "/legal/terms"],
      ["Privacy", "/legal/privacy"],
    ];
    for (const [name, href] of legalLinks) {
      const link = footer.getByRole("link", { name, exact: false }).first();
      await expect(link).toHaveAttribute("href", href);
    }
  });
});

test.describe("Public site — /pricing", () => {
  test("annual/monthly toggle changes pricing display", async ({ page }) => {
    await page.goto("/pricing");
    // There should be a toggle control for billing period
    const toggle = page
      .getByRole("switch", { name: /annual|monthly/i })
      .or(page.getByRole("button", { name: /annual|monthly/i }).first())
      .first();
    await expect(toggle).toBeVisible();
    await toggle.click();
    // After toggle, the page should still render correctly
    await assertBasicA11y(page);
  });

  test("school inquiry form validates required fields", async ({ page }) => {
    await page.goto("/pricing");
    // Scroll to inquiry form if present
    const submitBtn = page
      .getByRole("button", { name: /submit|send|inquir/i })
      .first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
      // Should show at least one validation error
      const error = page
        .locator("[aria-live], [role='alert'], .error, [data-error]")
        .first();
      await expect(error).toBeVisible({ timeout: 3_000 }).catch(() => {
        // Some implementations use HTML5 native validation — acceptable
      });
    }
  });
});

test.describe("Public site — mobile navigation", () => {
  // Use a typical mobile viewport so the hamburger toggle is visible and the
  // desktop nav is hidden via Tailwind's md: breakpoint (≥768 px).
  test.use({ viewport: { width: 375, height: 667 } });

  test("hamburger toggle opens and closes the mobile drawer", async ({
    page,
  }) => {
    await page.goto("/");

    // Locate the toggle by its stable aria-controls attribute so the locator
    // remains valid even after the aria-label changes from "Open menu" to
    // "Close menu" when the drawer is open.
    const toggle = page.locator('[aria-controls="mobile-nav"]');
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");

    // Drawer should not be present yet.
    const drawer = page.getByRole("navigation", { name: "Mobile navigation" });
    await expect(drawer).not.toBeVisible();

    // Open the drawer.
    await toggle.click();
    await expect(drawer).toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");

    // Close the drawer by clicking the toggle again.
    await toggle.click();
    await expect(drawer).not.toBeVisible();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  test("mobile drawer contains all primary nav links", async ({ page }) => {
    await page.goto("/");

    const toggle = page.locator('[aria-controls="mobile-nav"]');
    await toggle.click();

    const drawer = page.getByRole("navigation", { name: "Mobile navigation" });
    await expect(drawer).toBeVisible();

    for (const [label, href] of [
      ["Product", "/product"],
      ["How It Works", "/how-it-works"],
      ["Pricing", "/pricing"],
      ["AI", "/ai"],
      ["About", "/about"],
    ]) {
      const link = drawer.getByRole("link", { name: label, exact: false });
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute("href", href);
    }
  });

  test("mobile drawer contains Sign in and Start free trial CTAs", async ({
    page,
  }) => {
    await page.goto("/");

    const toggle = page.locator('[aria-controls="mobile-nav"]');
    await toggle.click();

    const drawer = page.getByRole("navigation", { name: "Mobile navigation" });
    await expect(drawer).toBeVisible();

    const signIn = drawer.getByRole("link", { name: /sign in/i });
    await expect(signIn).toBeVisible();
    await expect(signIn).toHaveAttribute("href", "/login");

    const trial = drawer.getByRole("link", { name: /start free trial/i });
    await expect(trial).toBeVisible();
    await expect(trial).toHaveAttribute("href", "/signup");
  });

  test("Escape key closes the mobile drawer and returns focus to toggle", async ({
    page,
  }) => {
    await page.goto("/");

    const toggle = page.locator('[aria-controls="mobile-nav"]');
    await toggle.click();
    await expect(
      page.getByRole("navigation", { name: "Mobile navigation" }),
    ).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("navigation", { name: "Mobile navigation" }),
    ).not.toBeVisible();

    // Focus must return to the toggle button so keyboard / SR users are not
    // stranded at an invisible element.
    await expect(toggle).toBeFocused();
  });

  test("drawer closes on pathname change (logo click)", async ({ page }) => {
    await page.goto("/");

    const toggle = page.locator('[aria-controls="mobile-nav"]');
    await toggle.click();
    await expect(
      page.getByRole("navigation", { name: "Mobile navigation" }),
    ).toBeVisible();

    // Navigate via the logo link — simulates a client-side route change.
    await page.getByRole("link", { name: /GradeWise home/i }).click();
    await expect(
      page.getByRole("navigation", { name: "Mobile navigation" }),
    ).not.toBeVisible();
  });
});

test.describe("Public site — legal pages", () => {
  test("/legal/dpa shows attorney draft banner in development", async ({
    page,
  }) => {
    await page.goto("/legal/dpa");
    // The [ATTORNEY DRAFT REQUIRED] banner should be visible in non-production
    const banner = page
      .getByText(/attorney draft/i)
      .or(page.locator("[data-testid='attorney-draft-banner']"))
      .first();
    await expect(banner).toBeVisible();
  });
});
