import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiGet, apiPost, apiPut, apiPatch, apiDelete, ApiError, setAccessToken } from "@/lib/api/client";
import { setSessionToken } from "@/lib/auth/session";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  mockFetch.mockReset();
  // Reset access token between tests to avoid state leakage
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

/** Extract the Headers object passed as the second fetch argument. */
function getCallHeaders(callIndex: number): Headers {
  const init = mockFetch.mock.calls[callIndex][1] as RequestInit;
  const h = init.headers;
  if (h instanceof Headers) return h;
  // apiFetch always builds a `new Headers(...)` object, so this branch is
  // unreachable in practice; it satisfies the type-checker.
  return new Headers(h as HeadersInit);
}

describe("apiGet", () => {
  it("returns parsed JSON on success", async () => {
    mockFetch.mockReturnValueOnce(
      makeResponse({ data: { id: "1", name: "test" } }),
    );
    const result = await apiGet<{ id: string; name: string }>("/test");
    expect(result).toEqual({ id: "1", name: "test" });
  });

  it("throws ApiError with structured body on 404", async () => {
    const makeNotFoundResponse = () =>
      makeResponse({ error: { code: "NOT_FOUND", message: "Not found" } }, 404);
    mockFetch
      .mockReturnValueOnce(makeNotFoundResponse())
      .mockReturnValueOnce(makeNotFoundResponse());
    await expect(apiGet("/missing")).rejects.toBeInstanceOf(ApiError);
    await expect(apiGet("/missing")).rejects.toMatchObject({
      status: 404,
      code: "NOT_FOUND",
    });
  });

  it("throws ApiError with UNKNOWN_ERROR when response body is not JSON", async () => {
    mockFetch.mockReturnValueOnce(
      Promise.resolve(
        new Response("Internal Server Error", {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        }),
      ),
    );
    await expect(apiGet("/broken")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("apiPost", () => {
  it("sends JSON body and returns parsed response", async () => {
    mockFetch.mockReturnValueOnce(makeResponse({ data: { created: true } }, 201));
    const result = await apiPost<{ created: boolean }>("/items", { name: "x" });
    expect(result).toEqual({ created: true });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/items"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "x" }),
      }),
    );
  });
});

describe("apiPut", () => {
  it("sends PUT with body and returns parsed response", async () => {
    mockFetch.mockReturnValueOnce(makeResponse({ data: { updated: true } }));
    const result = await apiPut<{ updated: boolean }>("/items/1", { name: "updated" });
    expect(result).toEqual({ updated: true });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/items/1"),
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ name: "updated" }),
      }),
    );
  });
});

describe("apiPatch", () => {
  it("sends PATCH with body", async () => {
    mockFetch.mockReturnValueOnce(makeResponse({ data: { updated: true } }));
    await apiPatch("/items/1", { score: 5 });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/items/1"),
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});

describe("apiDelete", () => {
  it("handles 204 No Content", async () => {
    mockFetch.mockReturnValueOnce(
      Promise.resolve(new Response(null, { status: 204 })),
    );
    const result = await apiDelete("/items/1");
    expect(result).toBeUndefined();
  });
});

describe("ApiError", () => {
  it("exposes status, code, and message", () => {
    const err = new ApiError(403, {
      code: "FORBIDDEN",
      message: "Access denied",
    });
    expect(err.status).toBe(403);
    expect(err.code).toBe("FORBIDDEN");
    expect(err.message).toBe("Access denied");
  });

  it("exposes optional field", () => {
    const err = new ApiError(422, {
      code: "VALIDATION_ERROR",
      message: "Invalid input",
      field: "email",
    });
    expect(err.field).toBe("email");
  });
});

describe("setAccessToken", () => {
  it("attaches Authorization Bearer header when a token is set", async () => {
    setAccessToken("test-access-token");
    mockFetch.mockReturnValueOnce(makeResponse({ data: { id: "1" } }));
    await apiGet("/secure");
    expect(getCallHeaders(0).get("Authorization")).toBe("Bearer test-access-token");
  });

  it("omits Authorization header when no token is set", async () => {
    mockFetch.mockReturnValueOnce(makeResponse({ data: { id: "1" } }));
    await apiGet("/public");
    expect(getCallHeaders(0).has("Authorization")).toBe(false);
  });
});

describe("401 silent refresh", () => {
  it("retries the request with a new token after a successful silent refresh", async () => {
    // First call: 401 (token expired)
    mockFetch.mockReturnValueOnce(
      makeResponse({ error: { code: "TOKEN_EXPIRED", message: "Expired" } }, 401),
    );
    // Second call: refresh succeeds, returning new access token
    mockFetch.mockReturnValueOnce(
      makeResponse({ data: { access_token: "new-token", token_type: "bearer" } }),
    );
    // Third call: retried original request succeeds
    mockFetch.mockReturnValueOnce(makeResponse({ data: { id: "1" } }));

    const result = await apiGet<{ id: string }>("/protected");

    expect(result).toEqual({ id: "1" });
    expect(mockFetch).toHaveBeenCalledTimes(3);
    // The retried request should carry the new token
    expect(getCallHeaders(2).get("Authorization")).toBe("Bearer new-token");
  });

  it("throws ApiError and does not retry when refresh fails", async () => {
    // First call: 401
    mockFetch.mockReturnValueOnce(
      makeResponse({ error: { code: "TOKEN_EXPIRED", message: "Expired" } }, 401),
    );
    // Refresh call: also fails
    mockFetch.mockReturnValueOnce(
      makeResponse({ error: { code: "REFRESH_TOKEN_INVALID", message: "Invalid" } }, 401),
    );

    await expect(apiGet("/protected")).rejects.toBeInstanceOf(ApiError);
    // Only two fetch calls: original + refresh attempt (no retry)
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("redirects to /login when refresh fails", async () => {
    const replaceSpy = vi.fn();
    vi.stubGlobal("window", { location: { replace: replaceSpy } });

    mockFetch.mockReturnValueOnce(
      makeResponse({ error: { code: "TOKEN_EXPIRED", message: "Expired" } }, 401),
    );
    mockFetch.mockReturnValueOnce(
      makeResponse({ error: { code: "REFRESH_TOKEN_INVALID", message: "Invalid" } }, 401),
    );

    await expect(apiGet("/protected")).rejects.toBeInstanceOf(ApiError);
    expect(replaceSpy).toHaveBeenCalledWith("/login");
  });

  it("does not attempt refresh on 401 from auth endpoints", async () => {
    mockFetch.mockReturnValueOnce(
      makeResponse({ error: { code: "UNAUTHORIZED", message: "Bad creds" } }, 401),
    );

    await expect(apiPost("/auth/login", {})).rejects.toBeInstanceOf(ApiError);
    // Only one fetch call — no refresh attempt on auth paths
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("does not retry a retried request that returns 401 again", async () => {
    // First call: 401
    mockFetch.mockReturnValueOnce(
      makeResponse({ error: { code: "TOKEN_EXPIRED" } }, 401),
    );
    // Refresh succeeds
    mockFetch.mockReturnValueOnce(
      makeResponse({ data: { access_token: "new-token", token_type: "bearer" } }),
    );
    // Retried original: 401 again
    mockFetch.mockReturnValueOnce(
      makeResponse({ error: { code: "UNAUTHORIZED" } }, 401),
    );

    await expect(apiGet("/protected")).rejects.toBeInstanceOf(ApiError);
    // Three calls: original + refresh + retry (no further refresh on isRetry=true)
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });
});

