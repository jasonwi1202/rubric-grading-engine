import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ProductPage from "@/app/(public)/product/page";
import { PRODUCT_NAME } from "@/lib/constants";

// next/link renders as a standard <a> in the jsdom test environment.
// next/image renders as a standard <img> in the jsdom test environment.

describe("ProductPage", () => {
  it("renders without throwing", () => {
    expect(() => render(<ProductPage />)).not.toThrow();
  });

  describe("Page intro section", () => {
    it("renders exactly one h1", () => {
      render(<ProductPage />);
      const h1s = screen.getAllByRole("heading", { level: 1 });
      expect(h1s).toHaveLength(1);
    });

    it("renders text containing PRODUCT_NAME", () => {
      const { container } = render(<ProductPage />);
      expect(container.textContent).toContain(PRODUCT_NAME);
    });
  });

  describe("Feature deep-dive sections", () => {
    it("renders the AI grading engine section", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", { name: /ai grading engine/i }),
      ).toBeInTheDocument();
    });

    it("renders the human-in-the-loop review section", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", { name: /human-in-the-loop review/i }),
      ).toBeInTheDocument();
    });

    it("renders the student skill profiles section", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", { name: /student skill profiles/i }),
      ).toBeInTheDocument();
    });

    it("renders the class insights section", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", {
          name: /class insights and teacher worklist/i,
        }),
      ).toBeInTheDocument();
    });

    it("renders a screenshot placeholder image for each feature section", () => {
      render(<ProductPage />);
      const images = screen.getAllByRole("img");
      // Each feature section has one placeholder image
      expect(images.length).toBeGreaterThanOrEqual(4);
    });

    it("all screenshot images have non-empty alt text", () => {
      render(<ProductPage />);
      const images = screen.getAllByRole("img");
      images.forEach((img) => {
        expect(img).toHaveAttribute("alt");
        expect(img.getAttribute("alt")).not.toBe("");
      });
    });
  });

  describe("Trust and compliance callout", () => {
    it("renders the trust section heading", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", {
          name: /designed with trust and compliance in mind/i,
        }),
      ).toBeInTheDocument();
    });

    it("renders the FERPA compliant card", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", { name: /ferpa compliant/i }),
      ).toBeInTheDocument();
    });

    it("renders the no data selling card", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", { name: /no data selling/i }),
      ).toBeInTheDocument();
    });

    it("renders the teacher always in control card", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", { name: /teacher always in control/i }),
      ).toBeInTheDocument();
    });

    it("links the FERPA card to /legal/ferpa", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("link", { name: /read our ferpa notice/i }),
      ).toHaveAttribute("href", "/legal/ferpa");
    });

    it("links the privacy card to /legal/privacy", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("link", { name: /read our privacy policy/i }),
      ).toHaveAttribute("href", "/legal/privacy");
    });

    it("links the HITL card to /ai", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("link", { name: /read our ai transparency page/i }),
      ).toHaveAttribute("href", "/ai");
    });
  });

  describe("Bottom CTA section", () => {
    it("renders the CTA heading", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("heading", { name: /ready to see it in action/i }),
      ).toBeInTheDocument();
    });

    it("renders the CTA link to /signup with attribution param", () => {
      render(<ProductPage />);
      expect(
        screen.getByRole("link", {
          name: /start free trial — no credit card required/i,
        }),
      ).toHaveAttribute("href", "/signup?source=product_cta");
    });
  });
});
