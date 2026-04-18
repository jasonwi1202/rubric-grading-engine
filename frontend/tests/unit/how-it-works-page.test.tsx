import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import HowItWorksPage from "@/app/(public)/how-it-works/page";

// next/link renders as a standard <a> in the jsdom test environment.

describe("HowItWorksPage", () => {
  it("renders without throwing", () => {
    expect(() => render(<HowItWorksPage />)).not.toThrow();
  });

  describe("Page intro section", () => {
    it("renders exactly one h1", () => {
      render(<HowItWorksPage />);
      const h1s = screen.getAllByRole("heading", { level: 1 });
      expect(h1s).toHaveLength(1);
    });

    it("renders the page headline", () => {
      render(<HowItWorksPage />);
      expect(
        screen.getByRole("heading", { level: 1, name: /how it works/i }),
      ).toBeInTheDocument();
    });
  });

  describe("Workflow steps", () => {
    it("renders all seven step headings", () => {
      render(<HowItWorksPage />);
      expect(
        screen.getByRole("heading", { name: /build your rubric/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /create an assignment/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /upload essays/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /trigger ai grading/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /review and override/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /lock and share/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /see the patterns/i }),
      ).toBeInTheDocument();
    });

    it("renders a list element for each step", () => {
      render(<HowItWorksPage />);
      const list = screen.getByRole("list");
      const items = list.querySelectorAll("li");
      expect(items).toHaveLength(7);
    });
  });

  describe("Workflow stage labels", () => {
    it("renders the Upload stage label", () => {
      const { container } = render(<HowItWorksPage />);
      expect(container.textContent).toContain("Upload");
    });

    it("renders the Grade stage label", () => {
      const { container } = render(<HowItWorksPage />);
      expect(container.textContent).toContain("Grade");
    });

    it("renders the Export stage label", () => {
      const { container } = render(<HowItWorksPage />);
      expect(container.textContent).toContain("Export");
    });
  });

  describe("Bottom CTA section", () => {
    it("renders the CTA heading", () => {
      render(<HowItWorksPage />);
      expect(
        screen.getByRole("heading", { name: /ready to try it yourself/i }),
      ).toBeInTheDocument();
    });

    it("renders the CTA link to /signup with attribution param", () => {
      render(<HowItWorksPage />);
      expect(
        screen.getByRole("link", { name: /start free trial/i }),
      ).toHaveAttribute("href", "/signup?source=how_it_works_cta");
    });
  });
});
