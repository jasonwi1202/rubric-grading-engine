/**
 * Unit tests for middleware.ts — route protection and public-site auth redirects.
 *
 * Mocks `next/server` so tests run in the jsdom environment without requiring
 * the real Next.js Edge runtime.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { NextRequest } from "next/server";

// Sentinel value so we can assert NextResponse.next() was returned.
const NEXT_SENTINEL = { type: "next" } as const;

vi.mock("next/server", () => ({
  NextResponse: {
    next: vi.fn(() => NEXT_SENTINEL),
    redirect: vi.fn((url: URL) => ({ type: "redirect", url })),
  },
}));

// Import AFTER the mock is set up.
import { NextResponse } from "next/server";
import { middleware } from "@/middleware";

/**
 * Build a minimal mock NextRequest.
 *
 * The real NextRequest lives in the Edge runtime; here we provide exactly the
 * interface the middleware touches: `nextUrl` (with `pathname`, `search`,
 * `clone`) and `cookies.has`.
 */
function makeRequest(
  pathname: string,
  options: { hasCookie?: boolean; search?: string } = {},
) {
  const { hasCookie = false, search = "" } = options;
  const url = new URL(`http://localhost${pathname}${search}`);
  return {
    nextUrl: {
      pathname: url.pathname,
      search: url.search,
      clone: () => new URL(url.toString()),
    },
    cookies: {
      has: (name: string) => hasCookie && name === "refresh_token",
    },
  } as unknown as NextRequest;
}

describe("middleware", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ---------------------------------------------------------------------------
  // Unauthenticated user (no refresh_token cookie)
  // ---------------------------------------------------------------------------
  describe("unauthenticated user", () => {
    it("passes the root path through", () => {
      const result = middleware(makeRequest("/"));
      expect(result).toBe(NEXT_SENTINEL);
      expect(NextResponse.next).toHaveBeenCalledOnce();
    });

    it.each([
      "/product",
      "/how-it-works",
      "/pricing",
      "/about",
      "/ai",
      "/login",
      "/signup",
      "/legal/terms",
      "/legal/privacy",
      "/legal/ferpa",
      "/legal/dpa",
    ])("passes public path %s through", (path) => {
      const result = middleware(makeRequest(path));
      expect(result).toBe(NEXT_SENTINEL);
    });

    it("redirects /dashboard to /login with next= param", () => {
      middleware(makeRequest("/dashboard"));
      expect(NextResponse.redirect).toHaveBeenCalledOnce();
      const redirectUrl = vi.mocked(NextResponse.redirect).mock
        .calls[0][0] as URL;
      expect(redirectUrl.pathname).toBe("/login");
      expect(redirectUrl.searchParams.get("next")).toBe("/dashboard");
    });

    it("redirects /classes to /login with next= param", () => {
      middleware(makeRequest("/classes"));
      const redirectUrl = vi.mocked(NextResponse.redirect).mock
        .calls[0][0] as URL;
      expect(redirectUrl.pathname).toBe("/login");
      expect(redirectUrl.searchParams.get("next")).toBe("/classes");
    });

    it("preserves query string in next= param when redirecting a protected route", () => {
      middleware(
        makeRequest("/dashboard", { search: "?tab=worklist" }),
      );
      const redirectUrl = vi.mocked(NextResponse.redirect).mock
        .calls[0][0] as URL;
      expect(redirectUrl.pathname).toBe("/login");
      expect(redirectUrl.searchParams.get("next")).toBe(
        "/dashboard?tab=worklist",
      );
    });
  });

  // ---------------------------------------------------------------------------
  // Authenticated user (refresh_token cookie present)
  // ---------------------------------------------------------------------------
  describe("authenticated user", () => {
    it("redirects /login to /dashboard", () => {
      middleware(makeRequest("/login", { hasCookie: true }));
      expect(NextResponse.redirect).toHaveBeenCalledOnce();
      const redirectUrl = vi.mocked(NextResponse.redirect).mock
        .calls[0][0] as URL;
      expect(redirectUrl.pathname).toBe("/dashboard");
    });

    it("redirects /signup to /dashboard", () => {
      middleware(makeRequest("/signup", { hasCookie: true }));
      const redirectUrl = vi.mocked(NextResponse.redirect).mock
        .calls[0][0] as URL;
      expect(redirectUrl.pathname).toBe("/dashboard");
    });

    it("strips query string from the auth-entry redirect to /dashboard", () => {
      middleware(makeRequest("/login", { hasCookie: true, search: "?next=/classes" }));
      const redirectUrl = vi.mocked(NextResponse.redirect).mock
        .calls[0][0] as URL;
      expect(redirectUrl.pathname).toBe("/dashboard");
      expect(redirectUrl.search).toBe("");
    });

    it("passes public marketing paths through (e.g. /product)", () => {
      const result = middleware(makeRequest("/product", { hasCookie: true }));
      expect(result).toBe(NEXT_SENTINEL);
    });

    it("passes the root path through", () => {
      const result = middleware(makeRequest("/", { hasCookie: true }));
      expect(result).toBe(NEXT_SENTINEL);
    });

    it("passes /dashboard through without redirect", () => {
      const result = middleware(makeRequest("/dashboard", { hasCookie: true }));
      expect(result).toBe(NEXT_SENTINEL);
      expect(NextResponse.redirect).not.toHaveBeenCalled();
    });

    it("passes /classes through without redirect", () => {
      const result = middleware(makeRequest("/classes", { hasCookie: true }));
      expect(result).toBe(NEXT_SENTINEL);
    });
  });
});
