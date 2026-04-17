/**
 * Tests for /onboarding/rubric (Step 2 of the onboarding wizard).
 *
 * Covers:
 * - Choose mode renders the three options (scratch, templates, skip).
 * - "Build from scratch" shows the builder form.
 * - Selecting a template pre-fills the form with the template's criteria count.
 * - Submitting with empty rubric name shows a validation error.
 * - Successful submit calls the API and navigates to /onboarding/done.
 * - 401 from the API redirects to /login?next=/onboarding/rubric.
 * - Non-401/non-404/non-405 errors show a user-safe message.
 * - Skip button navigates to /onboarding/done without calling the API.
 *
 * No student PII in fixtures.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockPush = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));

const mockCreateRubric = vi.fn();
vi.mock("@/lib/api/rubrics", () => ({
  createRubric: (...args: unknown[]) => mockCreateRubric(...args),
}));

import OnboardingRubricPage from "@/app/(onboarding)/onboarding/rubric/page";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Render tests — choose mode (initial view)
// ---------------------------------------------------------------------------

describe("OnboardingRubricPage — choose mode", () => {
  it("renders the step indicator", () => {
    render(<OnboardingRubricPage />);
    expect(screen.getByText(/step 2 of 2/i)).toBeInTheDocument();
  });

  it("renders the 'Build from scratch' option", () => {
    render(<OnboardingRubricPage />);
    expect(screen.getByRole("button", { name: /build from scratch/i })).toBeInTheDocument();
  });

  it("renders all three template buttons", () => {
    render(<OnboardingRubricPage />);
    expect(screen.getByRole("button", { name: /5-paragraph essay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /argumentative writing/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /literary analysis/i })).toBeInTheDocument();
  });

  it("renders the skip link", () => {
    render(<OnboardingRubricPage />);
    expect(
      screen.getByRole("button", { name: /skip for now/i }),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Build mode — scratch
// ---------------------------------------------------------------------------

describe("OnboardingRubricPage — build from scratch", () => {
  it("shows the rubric name field after clicking 'Build from scratch'", async () => {
    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /build from scratch/i }));

    await waitFor(() => {
      expect(screen.getByLabelText(/rubric name/i)).toBeInTheDocument();
    });
  });

  it("renders 3 criteria rows by default (scratch mode)", async () => {
    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /build from scratch/i }));

    await waitFor(() => {
      // Each criterion has a name input labelled "Criterion N name"
      expect(screen.getByLabelText(/criterion 1 name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/criterion 2 name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/criterion 3 name/i)).toBeInTheDocument();
      expect(screen.queryByLabelText(/criterion 4 name/i)).not.toBeInTheDocument();
    });
  });

  it("shows validation error when rubric name is empty", async () => {
    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /build from scratch/i }));

    await waitFor(() => screen.getByRole("button", { name: /save rubric/i }));
    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    await waitFor(() => {
      expect(screen.getByText(/rubric name is required/i)).toBeInTheDocument();
    });
    expect(mockCreateRubric).not.toHaveBeenCalled();
  });

  it("calls createRubric and navigates to /onboarding/done on success", async () => {
    mockCreateRubric.mockResolvedValueOnce({ id: "rubric-uuid" });

    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /build from scratch/i }));

    await waitFor(() => screen.getByLabelText(/rubric name/i));
    await user.type(screen.getByLabelText(/rubric name/i), "My Rubric");
    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    await waitFor(() => {
      expect(mockCreateRubric).toHaveBeenCalledWith(
        expect.objectContaining({ name: "My Rubric" }),
      );
    });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/onboarding/done");
    });
  });
});

// ---------------------------------------------------------------------------
// Build mode — template
// ---------------------------------------------------------------------------

describe("OnboardingRubricPage — template selection", () => {
  it("renders 4 criteria rows after selecting the 5-Paragraph Essay template", async () => {
    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /5-paragraph essay/i }));

    await waitFor(() => {
      // Template has 4 criteria — all four inputs should be present
      expect(screen.getByLabelText(/criterion 1 name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/criterion 2 name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/criterion 3 name/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/criterion 4 name/i)).toBeInTheDocument();
    });
  });

  it("pre-fills rubric name with template name", async () => {
    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /argumentative writing/i }));

    await waitFor(() => {
      const nameInput = screen.getByLabelText(/rubric name/i) as HTMLInputElement;
      expect(nameInput.value).toBe("Argumentative Writing");
    });
  });
});

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

describe("OnboardingRubricPage — error handling", () => {
  it("redirects to /login with next param on 401", async () => {
    mockCreateRubric.mockRejectedValueOnce(
      new ApiError(401, { code: "UNAUTHORIZED", message: "Not authenticated." }),
    );

    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /build from scratch/i }));
    await waitFor(() => screen.getByLabelText(/rubric name/i));
    await user.type(screen.getByLabelText(/rubric name/i), "My Rubric");
    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login?next=/onboarding/rubric");
    });
  });

  it("advances to /onboarding/done on 404 (M3 not yet implemented)", async () => {
    mockCreateRubric.mockRejectedValueOnce(
      new ApiError(404, { code: "NOT_FOUND", message: "Endpoint not found." }),
    );

    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /build from scratch/i }));
    await waitFor(() => screen.getByLabelText(/rubric name/i));
    await user.type(screen.getByLabelText(/rubric name/i), "My Rubric");
    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/onboarding/done");
    });
  });

  it("shows user-safe error on non-401/non-404 API failure", async () => {
    mockCreateRubric.mockRejectedValueOnce(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server exploded." }),
    );

    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /build from scratch/i }));
    await waitFor(() => screen.getByLabelText(/rubric name/i));
    await user.type(screen.getByLabelText(/rubric name/i), "My Rubric");
    await user.click(screen.getByRole("button", { name: /save rubric/i }));

    await waitFor(() => {
      expect(screen.getByText(/failed to save rubric/i)).toBeInTheDocument();
    });
    // Raw error detail must never be shown
    expect(screen.queryByText("Server exploded.")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Skip
// ---------------------------------------------------------------------------

describe("OnboardingRubricPage — skip", () => {
  it("navigates to /onboarding/done without calling the API (choose mode)", async () => {
    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /skip for now/i }));

    expect(mockCreateRubric).not.toHaveBeenCalled();
    expect(mockPush).toHaveBeenCalledWith("/onboarding/done");
  });

  it("navigates to /onboarding/done without calling the API (build mode skip)", async () => {
    const user = userEvent.setup();
    render(<OnboardingRubricPage />);

    await user.click(screen.getByRole("button", { name: /build from scratch/i }));
    await waitFor(() => screen.getByRole("button", { name: /save rubric/i }));

    // There are two "skip for now" buttons in build mode
    const skipButtons = screen.getAllByRole("button", { name: /skip for now/i });
    await user.click(skipButtons[0]);

    expect(mockCreateRubric).not.toHaveBeenCalled();
    expect(mockPush).toHaveBeenCalledWith("/onboarding/done");
  });
});
