/**
 * Auth session helpers.
 *
 * The access token is kept in module-level memory — never written to
 * localStorage, sessionStorage, or a cookie. The refresh token is an
 * httpOnly Secure SameSite=Strict cookie that is managed exclusively by
 * the backend; the frontend never reads it directly.
 *
 * This module is intentionally independent of lib/api/client.ts so that
 * client.ts can import silentRefresh without creating a circular dependency.
 * Shared fetch logic (base URL, error/envelope parsing) lives in
 * lib/api/baseFetch.ts which neither module imports from the other.
 */

import { baseFetch } from "@/lib/api/baseFetch";

// Re-export ApiError so callers can catch it without a separate import.
export { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// In-memory access token store
// ---------------------------------------------------------------------------

let _accessToken: string | null = null;
let _refreshInFlight: Promise<string | null> | null = null;

/** Read the current in-memory access token. */
export function getAccessToken(): string | null {
  return _accessToken;
}

/** Store a new access token in memory, or clear it by passing null. */
export function setSessionToken(token: string | null): void {
  _accessToken = token;
}

// ---------------------------------------------------------------------------
// Auth API helpers
// ---------------------------------------------------------------------------

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

/**
 * Exchange credentials for an access token.
 * Stores the access token in memory and returns it.
 * Throws ApiError on network error or non-2xx response.
 */
export async function login(
  email: string,
  password: string,
): Promise<LoginResponse> {
  // baseFetch parses the { data: T } envelope and throws ApiError on non-2xx.
  const data = await baseFetch<LoginResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "include",
  });
  setSessionToken(data.access_token);
  return data;
}

/**
 * Attempt a silent token refresh using the httpOnly refresh cookie.
 * Returns the new access token on success, or null on failure.
 * Updates the in-memory token on success.
 */
export async function silentRefresh(): Promise<string | null> {
  // Multiple requests can receive 401 at once. Refresh token rotation is
  // single-use, so dedupe refresh calls to a single in-flight promise.
  if (_refreshInFlight) {
    return _refreshInFlight;
  }

  _refreshInFlight = (async () => {
    try {
      const data = await baseFetch<{ access_token: string }>("/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      setSessionToken(data.access_token);
      return data.access_token;
    } catch {
      return null;
    } finally {
      _refreshInFlight = null;
    }
  })();

  try {
    return await _refreshInFlight;
  } finally {
    // `_refreshInFlight` is cleared in the inner finally block above.
  }
}

/**
 * Invalidate the server-side refresh token and clear the in-memory access
 * token. Does not perform any client-side navigation — callers are
 * responsible for redirecting to /login.
 */
export async function logout(): Promise<void> {
  try {
    await baseFetch<void>("/auth/logout", {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Best-effort — clear local state even if the request fails.
  } finally {
    setSessionToken(null);
  }
}
