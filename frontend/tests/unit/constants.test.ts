import { describe, it, expect } from "vitest";
import { PRODUCT_NAME, SUPPORT_EMAIL } from "@/lib/constants";

describe("lib/constants", () => {
  describe("PRODUCT_NAME", () => {
    it("is a non-empty string", () => {
      expect(typeof PRODUCT_NAME).toBe("string");
      expect(PRODUCT_NAME.length).toBeGreaterThan(0);
    });
  });

  describe("SUPPORT_EMAIL", () => {
    it("is a valid email address format", () => {
      expect(typeof SUPPORT_EMAIL).toBe("string");
      expect(SUPPORT_EMAIL).toMatch(/^[^\s@]+@[^\s@]+\.[^\s@]+$/);
    });
  });
});
