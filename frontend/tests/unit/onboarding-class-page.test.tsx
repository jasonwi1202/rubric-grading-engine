/**
 * Tests for /onboarding/class (Step 1 of the onboarding wizard).
 *
 * Covers:
 * - Renders required form fields.
 * - Submitting with missing class name shows validation error.
 * - Successful submit calls the API and navigates to /onboarding/rubric.
 * - 401 from the API redirects to /login?next=/onboarding/class.
 * - Non-401 API errors show a user-safe message.
 * - Skip button navigates to /onboarding/rubric without calling the API.
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

const mockCreateClass = vi.fn();
vi.mock("@/lib/api/classes", () => ({
  createClass: (...args: unknown[]) => mockCreateClass(...args),
}));

import OnboardingClassPage from "@/app/(onboarding)/onboarding/class/page";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

async function fillClassName(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.type(screen.getByLabelText(/class name/i), name);
}

async function selectGradeLevel(user: ReturnType<typeof userEvent.setup>, grade: string) {
  await user.selectOptions(screen.getByLabelText(/grade level/i), grade);
}

// ---------------------------------------------------------------------------
// Render tests
// ---------------------------------------------------------------------------

describe("OnboardingClassPage — render", () => {
  it("renders the class name input", () => {
    render(<OnboardingClassPage />);
    expect(screen.getByLabelText(/class name/i)).toBeInTheDocument();
  });

  it("renders the grade level select", () => {
    render(<OnboardingClassPage />);
    expect(screen.getByLabelText(/grade level/i)).toBeInTheDocument();
  });

  it("renders the academic year select", () => {
    render(<OnboardingClassPage />);
    expect(screen.getByLabelText(/academic year/i)).toBeInTheDocument();
  });

  it("renders the submit button", () => {
    render(<OnboardingClassPage />);
    expect(screen.getByRole("button", { name: /create class/i })).toBeInTheDocument();
  });

  it("renders the skip link", () => {
    render(<OnboardingClassPage />);
    expect(screen.getByRole("button", { name: /i'll set up my class later/i })).toBeInTheDocument();
  });

  it("renders the step indicator", () => {
    render(<OnboardingClassPage />);
    expect(screen.getByText(/step 1 of 2/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Inline validation
// ---------------------------------------------------------------------------

describe("OnboardingClassPage — validation", () => {
  it("shows required error when form is submitted with empty class name", async () => {
    const user = userEvent.setup();
    render(<OnboardingClassPage />);

    await user.click(screen.getByRole("button", { name: /create class/i }));

    await waitFor(() => {
      expect(screen.getByText(/class name is required/i)).toBeInTheDocument();
    });
    expect(mockCreateClass).not.toHaveBeenCalled();
  });

  it("shows required error when grade level is not selected", async () => {
    const user = userEvent.setup();
    render(<OnboardingClassPage />);

    await user.type(screen.getByLabelText(/class name/i), "Period 3 English");
    await user.click(screen.getByRole("button", { name: /create class/i }));

    await waitFor(() => {
      expect(screen.getByText(/grade level is required/i)).toBeInTheDocument();
    });
    expect(mockCreateClass).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Successful submission
// ---------------------------------------------------------------------------

describe("OnboardingClassPage — successful submission", () => {
  it("calls createClass with correct values and navigates to /onboarding/rubric", async () => {
    mockCreateClass.mockResolvedValueOnce({ id: "class-uuid", name: "Period 3 English" });

    const user = userEvent.setup();
    render(<OnboardingClassPage />);

    await fillClassName(user, "Period 3 English");
    await selectGradeLevel(user, "Grade 9");
    await user.click(screen.getByRole("button", { name: /create class/i }));

    await waitFor(() => {
      expect(mockCreateClass).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Period 3 English",
          grade_level: "Grade 9",
        }),
      );
    });

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/onboarding/rubric");
    });
  });
});

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

describe("OnboardingClassPage — error handling", () => {
  it("redirects to /login with next param on 401", async () => {
    mockCreateClass.mockRejectedValueOnce(
      new ApiError(401, { code: "UNAUTHORIZED", message: "Not authenticated." }),
    );

    const user = userEvent.setup();
    render(<OnboardingClassPage />);

    await fillClassName(user, "Period 3 English");
    await selectGradeLevel(user, "Grade 9");
    await user.click(screen.getByRole("button", { name: /create class/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login?next=/onboarding/class");
    });
  });

  it("shows user-safe error on non-401 API failure", async () => {
    mockCreateClass.mockRejectedValueOnce(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server error." }),
    );

    const user = userEvent.setup();
    render(<OnboardingClassPage />);

    await fillClassName(user, "Period 3 English");
    await selectGradeLevel(user, "Grade 9");
    await user.click(screen.getByRole("button", { name: /create class/i }));

    await waitFor(() => {
      expect(screen.getByText(/failed to create class/i)).toBeInTheDocument();
    });
    // Raw API error detail must not be shown
    expect(screen.queryByText("Server error.")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Skip
// ---------------------------------------------------------------------------

describe("OnboardingClassPage — skip", () => {
  it("navigates to /onboarding/rubric without calling the API", async () => {
    const user = userEvent.setup();
    render(<OnboardingClassPage />);

    await user.click(screen.getByRole("button", { name: /i'll set up my class later/i }));

    expect(mockCreateClass).not.toHaveBeenCalled();
    expect(mockPush).toHaveBeenCalledWith("/onboarding/rubric");
  });
});
