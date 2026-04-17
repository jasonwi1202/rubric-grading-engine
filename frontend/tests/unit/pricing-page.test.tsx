import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import PricingContent from "@/app/(public)/pricing/_pricing-content";

// Mock the API call so the inquiry form doesn't attempt a real network request.
vi.mock("@/lib/api/contact", () => ({
  submitContactInquiry: vi.fn(),
}));

describe("PricingContent", () => {
  describe("Page structure", () => {
    it("renders exactly one h1", () => {
      render(<PricingContent />);
      const h1s = screen.getAllByRole("heading", { level: 1 });
      expect(h1s).toHaveLength(1);
    });

    it("renders the hero headline", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("heading", { name: /simple pricing for teachers/i }),
      ).toBeInTheDocument();
    });
  });

  describe("Billing toggle", () => {
    it("renders the Monthly billing button", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("button", { name: /monthly/i }),
      ).toBeInTheDocument();
    });

    it("renders the Annual billing button", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("button", { name: /annual/i }),
      ).toBeInTheDocument();
    });
  });

  describe("Pricing tiers", () => {
    it("renders the Trial tier heading", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("heading", { name: /trial/i }),
      ).toBeInTheDocument();
    });

    it("renders the Teacher tier heading", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("heading", { name: /^teacher$/i }),
      ).toBeInTheDocument();
    });

    it("renders the School tier heading", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("heading", { name: /^school$/i }),
      ).toBeInTheDocument();
    });

    it("renders the District tier heading", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("heading", { name: /^district$/i }),
      ).toBeInTheDocument();
    });
  });

  describe("Compare plans section", () => {
    it("renders the Compare plans heading", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("heading", { name: /compare plans/i }),
      ).toBeInTheDocument();
    });
  });

  describe("FAQ section", () => {
    it("renders the Frequently asked questions heading", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("heading", { name: /frequently asked questions/i }),
      ).toBeInTheDocument();
    });
  });

  describe("Inquiry form section", () => {
    it("renders the inquiry section heading", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("heading", { name: /school or district inquiry/i }),
      ).toBeInTheDocument();
    });

    it("renders the inquiry form", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("form", { name: /school and district inquiry form/i }),
      ).toBeInTheDocument();
    });

    it("renders the Send inquiry submit button", () => {
      render(<PricingContent />);
      expect(
        screen.getByRole("button", { name: /send inquiry/i }),
      ).toBeInTheDocument();
    });
  });
});
