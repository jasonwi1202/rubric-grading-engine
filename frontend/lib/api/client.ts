/**
 * Base API client — all backend communication goes through these typed fetch
 * wrappers. No raw `fetch()` calls in components or hooks.
 *
 * Auth: the access token is kept in memory via lib/auth/session.ts. The
 * refresh token is stored in an httpOnly Secure SameSite=Strict cookie and
 * is never readable by JavaScript. In the browser, `credentials: "include"`
 * forwards the refresh-token cookie automatically.
 *
 * On a 401 response (for any request that is not itself an auth endpoint),
 * the client attempts a silent token refresh. If the refresh succeeds the
 * original request is retried with the new token. If the refresh fails the
 * user is redirected to /login.
 *
 * Call `setAccessToken(token)` after a successful login to store the Bearer
 * token. Call `setAccessToken(null)` on logout.
 */
import {
  getAccessToken,
  setSessionToken,
  silentRefresh,
} from "@/lib/auth/session";

// ---------------------------------------------------------------------------
// Access token proxy — delegates to session.ts
// ---------------------------------------------------------------------------

/**
 * Store the access token in memory. Call after login; call with `null` on
 * logout. The token is attached as `Authorization: Bearer …` on every request.
 *
 * This is a convenience re-export so callers that already import from
 * `@/lib/api/client` do not need to change their import path.
 */
export function setAccessToken(token: string | null): void {
  setSessionToken(token);
}

// ---------------------------------------------------------------------------
// Error types
// ---------------------------------------------------------------------------

export interface ApiErrorBody {
  code: string;
  message: string;
  field?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly field?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.field = body.field;
  }
}

// ---------------------------------------------------------------------------
// Auth endpoint paths that must not trigger the 401-refresh cycle
// ---------------------------------------------------------------------------

const AUTH_PATHS = new Set(["/auth/login", "/auth/refresh", "/auth/logout"]);

// ---------------------------------------------------------------------------
// Internal fetch wrapper
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  isRetry = false,
): Promise<T> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!baseUrl) {
    throw new Error(
      `NEXT_PUBLIC_API_URL is not set. Cannot call ${path}. Add it to your .env.local file.`,
    );
  }

  const url = `${baseUrl}${path}`;

  const headers = new Headers(init.headers);
  // Only set Content-Type for requests that carry a body (POST/PUT/PATCH).
  // Setting it on GET/DELETE triggers unnecessary CORS preflight requests.
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...init,
    headers,
    credentials: "include",
  });

  // ----- 401 handling: attempt silent refresh then retry once -----
  if (
    response.status === 401 &&
    !isRetry &&
    !AUTH_PATHS.has(path)
  ) {
    const newToken = await silentRefresh();
    if (newToken) {
      // Retry the original request with the new token
      return apiFetch<T>(path, init, true);
    }
    // Refresh failed — redirect to login (client-side only)
    if (typeof window !== "undefined") {
      window.location.replace("/login");
    }
    throw new ApiError(401, {
      code: "UNAUTHORIZED",
      message: "Session expired. Please log in again.",
    });
  }

  if (!response.ok) {
    let errorBody: ApiErrorBody;
    try {
      const json = (await response.json()) as { error?: ApiErrorBody };
      errorBody = json.error ?? {
        code: "UNKNOWN_ERROR",
        message: response.statusText,
      };
    } catch {
      errorBody = { code: "UNKNOWN_ERROR", message: response.statusText };
    }
    throw new ApiError(response.status, errorBody);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as unknown as T;
  }

  // Unwrap the standard API response envelope: { data: T, meta?: ... }
  const json = (await response.json()) as { data: T };
  return json.data;
}

// ---------------------------------------------------------------------------
// Public helpers
// ---------------------------------------------------------------------------

export function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  return apiFetch<T>(path, { ...init, method: "GET" });
}

export function apiPost<T>(
  path: string,
  body: unknown,
  init?: RequestInit,
): Promise<T> {
  return apiFetch<T>(path, {
    ...init,
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function apiPut<T>(
  path: string,
  body: unknown,
  init?: RequestInit,
): Promise<T> {
  return apiFetch<T>(path, {
    ...init,
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function apiPatch<T>(
  path: string,
  body: unknown,
  init?: RequestInit,
): Promise<T> {
  return apiFetch<T>(path, {
    ...init,
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function apiDelete<T>(path: string, init?: RequestInit): Promise<T> {
  return apiFetch<T>(path, { ...init, method: "DELETE" });
}
