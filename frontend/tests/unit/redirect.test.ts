import { describe, it, expect } from "vitest";
import { isSafeRedirectPath } from "@/lib/utils/redirect";

describe("isSafeRedirectPath", () => {
  it("accepts a simple relative path", () => {
    expect(isSafeRedirectPath("/dashboard")).toBe(true);
  });

  it("accepts a nested relative path", () => {
    expect(isSafeRedirectPath("/classes/abc/assignments/123")).toBe(true);
  });

  it("accepts the root path", () => {
    expect(isSafeRedirectPath("/")).toBe(true);
  });

  it("rejects an empty string", () => {
    expect(isSafeRedirectPath("")).toBe(false);
  });

  it("rejects a path that does not start with /", () => {
    expect(isSafeRedirectPath("dashboard")).toBe(false);
    expect(isSafeRedirectPath("http://evil.com")).toBe(false);
    expect(isSafeRedirectPath("https://evil.com")).toBe(false);
  });

  it("rejects a protocol-relative URL (// prefix)", () => {
    expect(isSafeRedirectPath("//evil.com")).toBe(false);
    expect(isSafeRedirectPath("//evil.com/path")).toBe(false);
  });

  it("rejects paths containing backslashes", () => {
    expect(isSafeRedirectPath("/\\evil.com")).toBe(false);
    expect(isSafeRedirectPath("/path\\to")).toBe(false);
  });
});
