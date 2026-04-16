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
 */

// ---------------------------------------------------------------------------
// In-memory access token store
// ---------------------------------------------------------------------------

let _accessToken: string | null = null;

/** Read the current in-memory access token. */
export function getAccessToken(): string | null {
  return _accessToken;
}

/** Store a new access token in memory, or clear it by passing null. */
export function setSessionToken(token: string | null): void {
  _accessToken = token;
}

// ---------------------------------------------------------------------------
// Auth API helpers (raw fetch — no apiFetch to avoid circular imports)
// ---------------------------------------------------------------------------

function getBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not set. Add it to your .env.local file.",
    );
  }
  return url;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

/**
 * Exchange credentials for an access token.
 * Stores the access token in memory and returns it.
 * Throws on network error or non-2xx response.
 */
export async function login(
  email: string,
  password: string,
): Promise<LoginResponse> {
  const res = await fetch(`${getBaseUrl()}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "include",
  });

  if (!res.ok) {
    let message = "Login failed";
    try {
      const json = (await res.json()) as {
        error?: { message?: string; code?: string };
      };
      message = json.error?.message ?? message;
    } catch {
      // ignore parse error
    }
    throw new Error(message);
  }

  const json = (await res.json()) as { data: LoginResponse };
  const { access_token, token_type } = json.data;
  setSessionToken(access_token);
  return { access_token, token_type };
}

/**
 * Attempt a silent token refresh using the httpOnly refresh cookie.
 * Returns the new access token on success, or null on failure.
 * Updates the in-memory token on success.
 */
export async function silentRefresh(): Promise<string | null> {
  try {
    const res = await fetch(`${getBaseUrl()}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });

    if (!res.ok) return null;

    const json = (await res.json()) as {
      data: { access_token: string };
    };
    const token = json.data.access_token;
    setSessionToken(token);
    return token;
  } catch {
    return null;
  }
}

/**
 * Invalidate the server-side refresh token and clear the in-memory access
 * token. Does not perform any client-side navigation — callers are
 * responsible for redirecting to /login.
 */
export async function logout(): Promise<void> {
  try {
    await fetch(`${getBaseUrl()}/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Best-effort — clear local state even if the request fails.
  } finally {
    setSessionToken(null);
  }
}
