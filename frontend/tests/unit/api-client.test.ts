import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiGet, apiPost, apiPut, apiPatch, apiDelete, ApiError, setAccessToken } from "@/lib/api/client";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  mockFetch.mockReset();
  // Reset access token between tests to avoid state leakage
  setAccessToken(null);
});

function makeResponse(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
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
    const callHeaders = (mockFetch.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(callHeaders.get("Authorization")).toBe("Bearer test-access-token");
  });

  it("omits Authorization header when no token is set", async () => {
    mockFetch.mockReturnValueOnce(makeResponse({ data: { id: "1" } }));
    await apiGet("/public");
    const callHeaders = (mockFetch.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(callHeaders.has("Authorization")).toBe(false);
  });
});
