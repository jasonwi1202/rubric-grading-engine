import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getAccessToken,
  setSessionToken,
  silentRefresh,
  logout,
} from "@/lib/auth/session";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  mockFetch.mockReset();
  // Reset in-memory token between tests to avoid state leakage
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

describe("getAccessToken / setSessionToken", () => {
  it("returns null initially", () => {
    expect(getAccessToken()).toBeNull();
  });

  it("stores and retrieves a token", () => {
    setSessionToken("my-token");
    expect(getAccessToken()).toBe("my-token");
  });

  it("clears the token when set to null", () => {
    setSessionToken("my-token");
    setSessionToken(null);
    expect(getAccessToken()).toBeNull();
  });
});

describe("silentRefresh", () => {
  it("stores and returns the new access token on success", async () => {
    mockFetch.mockReturnValueOnce(
      makeResponse({ data: { access_token: "new-token", token_type: "bearer" } }),
    );

    const token = await silentRefresh();

    expect(token).toBe("new-token");
    expect(getAccessToken()).toBe("new-token");
  });

  it("returns null and leaves token unchanged on non-ok response", async () => {
    setSessionToken("old-token");
    mockFetch.mockReturnValueOnce(makeResponse({ error: { code: "REFRESH_TOKEN_INVALID" } }, 401));

    const token = await silentRefresh();

    expect(token).toBeNull();
    // In-memory token is not cleared by a failed refresh — the client handles
    // the redirect; the old token stays until explicitly cleared.
    expect(getAccessToken()).toBe("old-token");
  });

  it("returns null on fetch network error", async () => {
    mockFetch.mockRejectedValueOnce(new Error("Network error"));

    const token = await silentRefresh();

    expect(token).toBeNull();
  });

  it("calls the correct endpoint", async () => {
    mockFetch.mockReturnValueOnce(
      makeResponse({ data: { access_token: "t", token_type: "bearer" } }),
    );

    await silentRefresh();

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/auth/refresh"),
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });
});

describe("logout", () => {
  it("clears the in-memory token", async () => {
    setSessionToken("existing-token");
    mockFetch.mockReturnValueOnce(
      Promise.resolve(new Response(null, { status: 204 })),
    );

    await logout();

    expect(getAccessToken()).toBeNull();
  });

  it("clears the token even if the logout request fails", async () => {
    setSessionToken("existing-token");
    mockFetch.mockRejectedValueOnce(new Error("Network error"));

    await logout();

    expect(getAccessToken()).toBeNull();
  });

  it("calls the logout endpoint", async () => {
    mockFetch.mockReturnValueOnce(
      Promise.resolve(new Response(null, { status: 204 })),
    );

    await logout();

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/auth/logout"),
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });
});
