import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import AboutPage from "@/app/(public)/about/page";
import { PRODUCT_NAME, SUPPORT_EMAIL } from "@/lib/constants";

// next/link renders as a standard <a> in the jsdom test environment.

describe("AboutPage", () => {
  it("renders without throwing", () => {
    expect(() => render(<AboutPage />)).not.toThrow();
  });

  describe("Mission statement section", () => {
    it("renders exactly one h1", () => {
      render(<AboutPage />);
      const h1s = screen.getAllByRole("heading", { level: 1 });
      expect(h1s).toHaveLength(1);
    });

    it("renders text containing PRODUCT_NAME", () => {
      const { container } = render(<AboutPage />);
      expect(container.textContent).toContain(PRODUCT_NAME);
    });

    it("renders the mission statement heading", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("heading", { name: /our mission/i }),
      ).toBeInTheDocument();
    });
  });

  describe("Core principles section", () => {
    it("renders the 'What we stand for' heading", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("heading", { name: /what we stand for/i }),
      ).toBeInTheDocument();
    });

    it("renders the Human-in-the-loop principle", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("heading", { name: /human-in-the-loop, always/i }),
      ).toBeInTheDocument();
    });

    it("renders the teacher agency principle", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("heading", { name: /teacher agency first/i }),
      ).toBeInTheDocument();
    });

    it("renders the no student data sold principle", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("heading", { name: /student data is never sold/i }),
      ).toBeInTheDocument();
    });

    it("renders the FERPA principle", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("heading", { name: /ferpa is a hard requirement/i }),
      ).toBeInTheDocument();
    });
  });

  describe("Team placeholder section", () => {
    it("renders the 'Who built it' heading", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("heading", { name: /who built it/i }),
      ).toBeInTheDocument();
    });
  });

  describe("Contact callout section", () => {
    it("renders the 'Get in touch' heading", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("heading", { name: /get in touch/i }),
      ).toBeInTheDocument();
    });

    it("renders an email link with the support address", () => {
      render(<AboutPage />);
      const emailLink = screen.getByRole("link", { name: /email us/i });
      expect(emailLink).toHaveAttribute("href", `mailto:${SUPPORT_EMAIL}`);
    });

    it("renders a link to the FERPA notice", () => {
      render(<AboutPage />);
      expect(
        screen.getByRole("link", { name: /read our ferpa notice/i }),
      ).toHaveAttribute("href", "/legal/ferpa");
    });
  });
});
