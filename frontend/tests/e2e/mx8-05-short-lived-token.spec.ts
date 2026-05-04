/**
 * M8-05 — Deterministic short-lived token mode E2E test.
 *
 * Validates the token-expiry → silent-refresh recovery path using the
 * test-only `SHORT_LIVED_TOKEN_TTL_SECONDS` backend setting.  When that
 * setting is active, every login issues a JWT that expires in a few seconds
 * instead of the default 15 minutes, making it possible to exercise real
 * expiry events deterministically in CI without waiting.
 *
 * Acceptance criteria covered:
 * - Expired access tokens return HTTP 401 from authenticated endpoints.
 * - Missing access tokens return HTTP 401 from authenticated endpoints.
 * - The /auth/refresh endpoint with a valid refresh cookie returns HTTP 200
 *   and a fresh access token (proving the server-side refresh path works).
 * - The browser silent-refresh path recovers transparently: after the token
 *   expires, the next authenticated action succeeds without a redirect to
 *   /login, confirming the API client's 401 → silentRefresh() → retry cycle.
 *
 * Skip conditions:
 * - All tests are automatically skipped when the backend is NOT running in
 *   short-lived token mode.  Probe is performed by decoding the JWT `exp`/`iat`
 *   claims after login: if `exp − iat > SHORT_TTL_THRESHOLD_SECONDS` the
 *   feature is inactive and the suite is skipped gracefully.
 *
 * Local dev usage:
 *   Set `SHORT_LIVED_TOKEN_TTL_SECONDS=3` in your .env (or docker-compose
 *   override) and restart the backend container, then run:
 *     cd frontend && npx playwright test mx8-05-short-lived-token
 *
 * CI usage:
 *   Add `SHORT_LIVED_TOKEN_TTL_SECONDS=3` to your .env.ci or the Docker
 *   Compose environment section for the shard that runs this spec.
 *   All other specs are unaffected because their JWTs use the standard 15-min
 *   TTL (the setting is not set in those shards).
 *
 * Security:
 * - No student PII in any fixture — synthetic names and IDs only.
 * - No credential-format strings — all test credentials are clearly synthetic.
 * - SHORT_LIVED_TOKEN_TTL_SECONDS is blocked in staging/production by the
 *   backend startup validator; this feature cannot be activated outside of
 *   development/CI environments.
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { seedTeacher, loginApiWithCookie } from "./helpers";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

/**
 * Maximum TTL (seconds) that qualifies as "short-lived" for probe purposes.
 * If `exp − iat` from a freshly issued JWT exceeds this value the mode is
 * considered inactive and the suite skips.
 */
const SHORT_TTL_THRESHOLD_SECONDS = 30;

// ---------------------------------------------------------------------------
// Probe helper
// ---------------------------------------------------------------------------

/**
 * Decode the payload section of a JWT without verifying the signature.
 * Only used to read public claims (`exp`, `iat`) for probe/skip logic.
 */
function decodeJwtPayload(token: string): { exp: number; iat: number } {
  const parts = token.split(".");
  if (parts.length !== 3) {
    throw new Error("decodeJwtPayload: token does not have three parts");
  }
  // JWTs (RFC 7519) always use base64url encoding for the payload section.
  // Node.js Buffer decodes base64url when the encoding is "base64url".
  const json = Buffer.from(parts[1], "base64url").toString("utf8");
  return JSON.parse(json) as { exp: number; iat: number };
}

/**
 * Probe whether the backend is running in short-lived token mode.
 *
 * Returns `{ active: true, ttlSeconds }` when `exp − iat` of a freshly
 * issued JWT is ≤ SHORT_TTL_THRESHOLD_SECONDS, or `{ active: false, ttlSeconds: 0 }`
 * when the standard 15-min TTL is detected or the login call fails.
 */
async function probeShortLivedMode(
  email: string,
  password: string,
): Promise<{ active: boolean; ttlSeconds: number }> {
  try {
    const { accessToken } = await loginApiWithCookie(email, password);
    const { exp, iat } = decodeJwtPayload(accessToken);
    const ttlSeconds = exp - iat;
    return { active: ttlSeconds <= SHORT_TTL_THRESHOLD_SECONDS, ttlSeconds };
  } catch {
    return { active: false, ttlSeconds: 0 };
  }
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe("M8-05 — Short-lived token mode: token expiry & silent refresh", () => {
  test.describe.configure({ mode: "serial", timeout: 120_000 });
  test.setTimeout(120_000);

  const state: {
    email: string;
    password: string;
    modeActive: boolean;
    ttlSeconds: number;
    context: BrowserContext | null;
    page: Page | null;
  } = {
    email: "",
    password: "",
    modeActive: false,
    ttlSeconds: 0,
    context: null,
    page: null,
  };

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(120_000);

    // Create a verified teacher account to use for all tests.
    const creds = await seedTeacher("m8-05-short-token");
    state.email = creds.email;
    state.password = creds.password;

    // Probe whether the backend is running in short-lived mode.
    const probe = await probeShortLivedMode(state.email, state.password);
    state.modeActive = probe.active;
    state.ttlSeconds = probe.ttlSeconds;

    if (!state.modeActive) {
      // Short-lived mode is not active; no browser setup needed.
      return;
    }

    // Prepare a browser context for the browser-based silent-refresh test.
    state.context = await browser.newContext({
      baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    });
    state.page = await state.context.newPage();
  });

  test.afterAll(async () => {
    await state.context?.close();
  });

  // ── Helper: per-test skip guard ──────────────────────────────────────────

  function skipUnlessActive() {
    test.skip(
      !state.modeActive,
      `SHORT_LIVED_TOKEN_TTL_SECONDS is not active (detected TTL: ${state.ttlSeconds}s > ${SHORT_TTL_THRESHOLD_SECONDS}s). ` +
        "Set SHORT_LIVED_TOKEN_TTL_SECONDS=3 in the backend environment to enable this spec.",
    );
  }

  // ── Test 1: probe is detectable ──────────────────────────────────────────

  test("short-lived mode: backend issues tokens with a sub-30-second TTL", async () => {
    skipUnlessActive();
    // If we reach here without skipping, the probe already confirmed the TTL
    // is short.  Assert it for clarity.
    expect(state.ttlSeconds).toBeGreaterThanOrEqual(1);
    expect(state.ttlSeconds).toBeLessThanOrEqual(SHORT_TTL_THRESHOLD_SECONDS);
  });

  // ── Test 2: expired token → 401 ──────────────────────────────────────────

  test("expired access token returns HTTP 401 from an authenticated endpoint", async () => {
    skipUnlessActive();

    const { accessToken } = await loginApiWithCookie(state.email, state.password);

    // Wait for the token to expire (TTL + 1 s margin).
    await new Promise((resolve) =>
      setTimeout(resolve, (state.ttlSeconds + 1) * 1000),
    );

    // Any authenticated endpoint should return 401 with the expired token.
    const res = await fetch(`${API_BASE}/api/v1/classes`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    expect(res.status).toBe(401);
    const body = (await res.json()) as { error: { code: string } };
    expect(body.error.code).toBe("UNAUTHORIZED");
  });

  // ── Test 3: missing token → 401 ──────────────────────────────────────────

  test("request with no Authorization header returns HTTP 401", async () => {
    skipUnlessActive();

    const res = await fetch(`${API_BASE}/api/v1/classes`);
    expect(res.status).toBe(401);
    const body = (await res.json()) as { error: { code: string } };
    expect(body.error.code).toBe("UNAUTHORIZED");
  });

  // ── Test 4: refresh endpoint with valid cookie → 200 + new token ─────────

  test("POST /auth/refresh with valid refresh cookie issues a new access token", async () => {
    skipUnlessActive();

    // Login and capture the refresh token cookie.
    const { refreshToken } = await loginApiWithCookie(state.email, state.password);

    // Wait for the access token to expire.
    await new Promise((resolve) =>
      setTimeout(resolve, (state.ttlSeconds + 1) * 1000),
    );

    // Call the refresh endpoint with the refresh cookie in the Cookie header.
    const refreshRes = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { Cookie: `refresh_token=${refreshToken}` },
    });

    expect(refreshRes.status).toBe(200);
    const refreshBody = (await refreshRes.json()) as {
      data: { access_token: string };
    };
    expect(typeof refreshBody.data.access_token).toBe("string");
    expect(refreshBody.data.access_token.length).toBeGreaterThan(0);

    // The new token must itself be valid (decodeable and not yet expired).
    const { exp, iat } = decodeJwtPayload(refreshBody.data.access_token);
    expect(exp).toBeGreaterThan(iat);
  });

  // ── Test 5: browser silent-refresh — UI recovers after token expiry ───────

  test("browser: UI recovers transparently after access token expiry via silent refresh", async () => {
    skipUnlessActive();
    if (!state.page || !state.context) {
      throw new Error("Browser context not initialized");
    }
    const page = state.page;

    // Log in via the UI form so the browser acquires the httpOnly refresh
    // cookie that is needed for the silent-refresh path.
    await page.goto("/login");
    await page.getByLabel(/email/i).first().fill(state.email);
    await page.getByLabel(/password/i).first().fill(state.password);
    await page.getByRole("button", { name: /sign in/i }).click();

    // Wait for the post-login redirect to a protected page.
    await expect(page).toHaveURL(/\/(dashboard|onboarding)/, {
      timeout: 15_000,
    });

    // Wait for the short-lived access token to expire (TTL + 1 s margin).
    await page.waitForTimeout((state.ttlSeconds + 1) * 1000);

    // Trigger an authenticated API call by performing a full page reload.
    // After reload the in-memory access token is gone; the first API call
    // returns 401, which causes the client's silentRefresh() to fire.
    // If the refresh cookie is valid the token is renewed and the request is
    // retried — the page should load without redirecting to /login.
    await page.reload();

    // The page must remain on the protected route (not redirected to /login),
    // which confirms that silent refresh succeeded.
    await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });

    // Confirm the page displays authenticated content: a level-1 heading is
    // only present on protected routes (dashboard "Your Worklist", onboarding
    // step headings, etc.) and is absent on the login page.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 15_000,
    });
  });
});
