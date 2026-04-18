/**
 * Unit tests for the onboarding API helpers (lib/api/onboarding.ts).
 *
 * Tests verify that the correct endpoint paths and HTTP methods are used,
 * and that responses are unwrapped correctly.
 *
 * No real student PII in fixtures.  All fetch calls are mocked.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getOnboardingStatus, completeOnboarding } from "@/lib/api/onboarding";
import { setAccessToken } from "@/lib/api/client";
import { setSessionToken } from "@/lib/auth/session";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  mockFetch.mockReset();
  // Set a fake access token so the client attaches an Authorization header.
  setAccessToken("test-access-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
  setSessionToken(null);
});

function makeResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

// ---------------------------------------------------------------------------
// getOnboardingStatus
// ---------------------------------------------------------------------------

describe("getOnboardingStatus", () => {
  it("calls GET /api/v1/onboarding/status and unwraps data", async () => {
    const payload = { step: 1, completed: false, trial_ends_at: null };
    mockFetch.mockResolvedValueOnce(makeResponse({ data: payload }));

    const result = await getOnboardingStatus();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/onboarding/status");
    expect((init as { method: string }).method).toBe("GET");
    expect(result).toEqual(payload);
  });

  it("returns completed=true with trial_ends_at when set", async () => {
    const trialEnd = "2026-05-17T00:00:00Z";
    const payload = { step: 2, completed: true, trial_ends_at: trialEnd };
    mockFetch.mockResolvedValueOnce(makeResponse({ data: payload }));

    const result = await getOnboardingStatus();

    expect(result.completed).toBe(true);
    expect(result.trial_ends_at).toBe(trialEnd);
  });

  it("throws ApiError on 401", async () => {
    mockFetch.mockResolvedValueOnce(
      makeResponse(
        { error: { code: "UNAUTHORIZED", message: "Not authenticated." } },
        401,
      ),
    );

    // Silent refresh will also fail — stub it.
    mockFetch.mockResolvedValueOnce(
      makeResponse(
        { error: { code: "REFRESH_TOKEN_INVALID", message: "Bad refresh." } },
        401,
      ),
    );

    await expect(getOnboardingStatus()).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// completeOnboarding
// ---------------------------------------------------------------------------

describe("completeOnboarding", () => {
  it("calls POST /api/v1/onboarding/complete and unwraps data", async () => {
    const payload = { message: "Onboarding marked as complete." };
    mockFetch.mockResolvedValueOnce(makeResponse({ data: payload }));

    const result = await completeOnboarding();

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/onboarding/complete");
    expect((init as { method: string }).method).toBe("POST");
    expect(result).toEqual(payload);
  });
});
