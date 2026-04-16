/**
 * Base API client — all backend communication goes through these typed fetch
 * wrappers. No raw `fetch()` calls in components or hooks.
 *
 * Auth: the access token is read from a session cookie (httpOnly on the server;
 * the client reads the non-httpOnly NEXT_PUBLIC_* version for optimistic UI).
 * The underlying cookie is forwarded automatically when running in Server
 * Components; on the client side we include `credentials: "include"`.
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

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
  const url = `${API_BASE_URL}${path}`;

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(init.headers ?? {}),
  };

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

  return response.json() as Promise<T>;
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
