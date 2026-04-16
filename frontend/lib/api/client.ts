/**
 * Base API client — all backend communication goes through these typed fetch
 * wrappers. No raw `fetch()` calls in components or hooks.
 *
 * Auth: the access token is kept in memory (returned in the login response
 * body and held in React state / React Query cache). The refresh token is
 * stored in an httpOnly Secure SameSite=Strict cookie and is never readable
 * by JavaScript. On the client side we include `credentials: "include"` so
 * the refresh-token cookie is forwarded automatically; Server Components
 * forward cookies via `next/headers`.
 *
 * Call `setAccessToken(token)` after a successful login to attach the Bearer
 * token to all subsequent requests. Call `setAccessToken(null)` on logout.
 */

// ---------------------------------------------------------------------------
// Access token state — kept in module scope (memory only; never persisted)
// ---------------------------------------------------------------------------

let _accessToken: string | null = null;

/**
 * Store the access token in memory. Call after login; call with `null` on
 * logout. The token is attached as `Authorization: Bearer …` on every request.
 */
export function setAccessToken(token: string | null): void {
  _accessToken = token;
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
// Internal fetch wrapper
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!baseUrl) {
    throw new Error(
      `NEXT_PUBLIC_API_URL is not set. Cannot call ${path}. Add it to your .env.local file.`,
    );
  }

  const url = `${baseUrl}${path}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init.headers as Record<string, string>) ?? {}),
  };

  if (_accessToken) {
    headers["Authorization"] = `Bearer ${_accessToken}`;
  }

  const response = await fetch(url, {
    ...init,
    headers,
    credentials: "include",
  });

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
