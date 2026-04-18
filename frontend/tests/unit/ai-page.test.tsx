import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import AiPage from "@/app/(public)/ai/page";

// next/link renders as a standard <a> in the jsdom test environment.

describe("AiPage", () => {
  it("renders without throwing", () => {
    expect(() => render(<AiPage />)).not.toThrow();
  });

  describe("Hero section", () => {
    it("renders exactly one h1", () => {
      render(<AiPage />);
      const h1s = screen.getAllByRole("heading", { level: 1 });
      expect(h1s).toHaveLength(1);
    });

    it("renders the hero headline", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", {
          level: 1,
          name: /ai that assists\. teachers who decide\./i,
        }),
      ).toBeInTheDocument();
    });
  });

  describe("How the AI grades section", () => {
    it("renders the section heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", { name: /how the ai grades/i }),
      ).toBeInTheDocument();
    });

    it("renders all five grading step headings", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", { name: /reads your rubric criteria/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", {
          name: /scores each criterion independently/i,
        }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /writes a justification per criterion/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /generates overall feedback/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: /teacher reviews and approves/i }),
      ).toBeInTheDocument();
    });
  });

  describe("What the AI can / cannot do section", () => {
    it("renders the capabilities section heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", {
          name: /what the ai can and cannot do/i,
        }),
      ).toBeInTheDocument();
    });

    it("renders the 'What the AI can do' sub-heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", { name: /what the ai can do/i }),
      ).toBeInTheDocument();
    });

    it("renders the 'What the AI cannot do' sub-heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", { name: /what the ai cannot do/i }),
      ).toBeInTheDocument();
    });

    it("lists 'make a grade final without teacher review' in the cannot-do list", () => {
      render(<AiPage />);
      expect(screen.getByText(/make a grade final without teacher review/i)).toBeInTheDocument();
    });
  });

  describe("HITL guarantee callout", () => {
    it("renders the HITL guarantee heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", {
          name: /the human-in-the-loop guarantee/i,
        }),
      ).toBeInTheDocument();
    });

    it("renders the 'Every grade requires your review' text", () => {
      render(<AiPage />);
      expect(
        screen.getByText(/every grade requires your review/i),
      ).toBeInTheDocument();
    });
  });

  describe("Data use disclosure section", () => {
    it("renders the student essays section heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", {
          name: /what happens to student essays/i,
        }),
      ).toBeInTheDocument();
    });

    it("discloses that essays are sent to the OpenAI API", () => {
      render(<AiPage />);
      expect(
        screen.getByText(/sent to the openai api for grading/i),
      ).toBeInTheDocument();
    });

    it("discloses that essays are not used for training", () => {
      const { container } = render(<AiPage />);
      expect(container.textContent).toMatch(/never use student essay content to train/i);
    });

    it("links to the FERPA Notice page", () => {
      render(<AiPage />);
      const ferpaLinks = screen.getAllByRole("link", { name: /ferpa notice/i });
      expect(ferpaLinks.length).toBeGreaterThan(0);
      expect(ferpaLinks[0]).toHaveAttribute("href", "/legal/ferpa");
    });

    it("links to the Privacy Policy page", () => {
      render(<AiPage />);
      const privacyLinks = screen.getAllByRole("link", {
        name: /privacy policy/i,
      });
      expect(privacyLinks.length).toBeGreaterThan(0);
      expect(privacyLinks[0]).toHaveAttribute("href", "/legal/privacy");
    });
  });

  describe("Confidence scores section", () => {
    it("renders the confidence scores heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", { name: /confidence scores/i }),
      ).toBeInTheDocument();
    });

    it("explains what low confidence means", () => {
      const { container } = render(<AiPage />);
      expect(container.textContent).toMatch(/low.confidence/i);
    });
  });

  describe("FAQ section", () => {
    it("renders the FAQ heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", { name: /questions and concerns/i }),
      ).toBeInTheDocument();
    });

    it("includes the 'What if the AI is wrong?' entry", () => {
      const { container } = render(<AiPage />);
      expect(container.textContent).toMatch(/what if the ai is wrong/i);
    });
  });

  describe("Bottom CTA section", () => {
    it("renders the CTA heading", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("heading", {
          name: /see how it works in practice/i,
        }),
      ).toBeInTheDocument();
    });

    it("renders the Start free trial CTA link with attribution param", () => {
      render(<AiPage />);
      const ctaLinks = screen.getAllByRole("link", { name: /start free trial/i });
      expect(ctaLinks.length).toBeGreaterThan(0);
      expect(ctaLinks[0]).toHaveAttribute(
        "href",
        "/signup?source=ai_transparency_cta",
      );
    });

    it("renders the 'See the full workflow' link", () => {
      render(<AiPage />);
      expect(
        screen.getByRole("link", { name: /see the full workflow/i }),
      ).toHaveAttribute("href", "/how-it-works");
    });
  });
});
