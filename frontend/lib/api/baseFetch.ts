/**
 * Minimal shared fetch helper — base URL resolution, API error parsing, and
 * response envelope unwrapping.
 *
 * Used by both lib/api/client.ts and lib/auth/session.ts so that auth calls
 * share the same error normalisation as regular API calls, without requiring
 * session.ts to import from client.ts (which would create a circular
 * dependency).
 *
 * Does NOT set an Authorization header. Callers that need authenticated
 * requests should use lib/api/client.ts instead.
 */
import { ApiError } from "@/lib/api/errors";
import type { ApiErrorBody } from "@/lib/api/errors";

/** Resolve and validate the API base URL from the environment. */
export function getBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) {
    throw new Error(
      "NEXT_PUBLIC_API_URL is not set. Add it to your .env.local file.",
    );
  }
  return url;
}

/**
 * Minimal fetch wrapper: resolves the base URL, parses the standard
 * `{ data: T }` response envelope, and converts non-2xx responses into
 * `ApiError` instances.
 *
 * Does NOT attach an Authorization header. Use lib/api/client.ts for
 * authenticated requests.
 */
export async function baseFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${getBaseUrl()}${path}`, init);

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

  if (response.status === 204) {
    // 204 No Content carries no body. Callers must use `baseFetch<void>()` for
    // endpoints that return 204 to preserve type safety.
    return undefined as unknown as T;
  }

  const json = (await response.json()) as { data: T };
  return json.data;
}
