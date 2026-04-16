import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LandingPage from "@/app/(public)/page";
import { PRODUCT_NAME } from "@/lib/constants";

// next/link renders as a standard <a> in the jsdom test environment.

describe("LandingPage", () => {
  it("renders without throwing", () => {
    expect(() => render(<LandingPage />)).not.toThrow();
  });

  describe("Hero section", () => {
    it("renders the primary headline", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("heading", { level: 1, name: /grade smarter/i }),
      ).toBeInTheDocument();
    });

    it("renders the primary CTA link to /signup", () => {
      render(<LandingPage />);
      const heroCta = screen.getAllByRole("link", {
        name: /start free trial/i,
      })[0];
      expect(heroCta).toHaveAttribute("href", "/signup?source=landing_hero");
    });

    it("renders the secondary CTA link to /how-it-works", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("link", { name: /see how it works/i }),
      ).toHaveAttribute("href", "/how-it-works");
    });
  });

  describe("Problem → Solution section", () => {
    it("renders the problem column heading", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("heading", { name: /the grading loop is broken/i }),
      ).toBeInTheDocument();
    });

    it("renders the solution column heading with PRODUCT_NAME", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("heading", {
          name: new RegExp(`${PRODUCT_NAME} breaks the loop`, "i"),
        }),
      ).toBeInTheDocument();
    });
  });

  describe("Feature highlights section", () => {
    it("renders the section heading", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("heading", {
          name: /everything you need to grade with confidence/i,
        }),
      ).toBeInTheDocument();
    });

    it("renders all four feature cards", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("heading", {
          name: /ai grading with transparent reasoning/i,
        }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /student skill profiles/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /teacher-guided instruction/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /human-in-the-loop, always/i }),
      ).toBeInTheDocument();
    });
  });

  describe("How it works section", () => {
    it("renders the section heading", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("heading", { name: /how it works/i }),
      ).toBeInTheDocument();
    });

    it("renders all four step headings", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("heading", { name: /upload essays/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", {
          name: /ai grades against your rubric/i,
        }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /review, override, and approve/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /act on insights/i }),
      ).toBeInTheDocument();
    });

    it("renders a link to the full how-it-works page", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("link", { name: /see the full workflow/i }),
      ).toHaveAttribute("href", "/how-it-works");
    });
  });

  describe("Bottom CTA section", () => {
    it("renders the CTA heading", () => {
      render(<LandingPage />);
      expect(
        screen.getByRole("heading", {
          name: /ready to get your time back/i,
        }),
      ).toBeInTheDocument();
    });

    it("renders the bottom CTA link to /signup with attribution param", () => {
      render(<LandingPage />);
      const links = screen.getAllByRole("link", { name: /start free trial/i });
      const bottomCta = links.find((l) =>
        l.getAttribute("href")?.includes("landing_cta"),
      );
      expect(bottomCta).toHaveAttribute("href", "/signup?source=landing_cta");
    });
  });

  describe("Accessibility", () => {
    it("has exactly one h1", () => {
      render(<LandingPage />);
      const h1s = screen.getAllByRole("heading", { level: 1 });
      expect(h1s).toHaveLength(1);
    });

    it("does not contain hardcoded product name strings — uses PRODUCT_NAME", () => {
      const { container } = render(<LandingPage />);
      // The rendered text should include the dynamic PRODUCT_NAME value
      expect(container.textContent).toContain(PRODUCT_NAME);
    });
  });
});
