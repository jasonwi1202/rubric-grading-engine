/**
 * Tests for the /signup page.
 *
 * Covers:
 * - Renders all required form fields.
 * - Inline Zod validation fires before submission.
 * - Successful submission calls the API and redirects to /signup/verify.
 * - 409 conflict shows the correct user-safe error.
 * - 429 rate-limit shows the correct user-safe error.
 * - No student PII is exposed in assertions.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockSignup = vi.fn();
vi.mock("@/lib/api/auth", () => ({
  signup: (...args: unknown[]) => mockSignup(...args),
}));

// Import after mocks
import SignupPage from "@/app/(auth)/signup/page";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fillValidForm(user: ReturnType<typeof userEvent.setup>) {
  return async () => {
    await user.type(screen.getByLabelText(/first name/i), "Alex");
    await user.type(screen.getByLabelText(/last name/i), "Smith");
    await user.type(screen.getByLabelText(/work email/i), "alex@school.edu");
    await user.type(screen.getByLabelText(/school or organisation/i), "Test High School");
    await user.type(screen.getByLabelText(/^password$/i), "SecurePass1");
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Render tests
// ---------------------------------------------------------------------------

describe("SignupPage — render", () => {
  it("renders all required form fields", () => {
    render(<SignupPage />);

    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/last name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/work email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/school or organisation/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
  });

  it("renders the submit button", () => {
    render(<SignupPage />);
    expect(screen.getByRole("button", { name: /create account/i })).toBeInTheDocument();
  });

  it("renders a link to the login page", () => {
    render(<SignupPage />);
    expect(screen.getByRole("link", { name: /sign in/i })).toHaveAttribute("href", "/login");
  });
});

// ---------------------------------------------------------------------------
// Inline validation
// ---------------------------------------------------------------------------

describe("SignupPage — inline validation", () => {
  it("shows required errors when form is submitted empty", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/first name is required/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/last name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/email is required/i)).toBeInTheDocument();
    expect(screen.getByText(/school name is required/i)).toBeInTheDocument();
    expect(screen.getByText(/password must be at least 8/i)).toBeInTheDocument();
  });

  it("shows error for invalid email format", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.type(screen.getByLabelText(/work email/i), "not-an-email");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    });
  });

  it("shows error for password without digit", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.type(screen.getByLabelText(/^password$/i), "OnlyLetters");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/at least one digit/i)).toBeInTheDocument();
    });
  });

  it("shows error for password without letter", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.type(screen.getByLabelText(/^password$/i), "12345678");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      // The validation error is rendered as role="alert"; the hint paragraph is not.
      const alerts = screen.getAllByRole("alert");
      const letterAlert = alerts.find((el) =>
        /at least one letter/i.test(el.textContent ?? ""),
      );
      expect(letterAlert).toBeTruthy();
    });
  });

  it("does not call the API when validation fails", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/first name is required/i)).toBeInTheDocument();
    });
    expect(mockSignup).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Successful submission
// ---------------------------------------------------------------------------

describe("SignupPage — successful submission", () => {
  it("calls signup API with correct values and redirects to /signup/verify", async () => {
    mockSignup.mockResolvedValueOnce({
      id: "uuid-123",
      email: "alex@school.edu",
      message: "Account created.",
      created_at: "2026-01-01T00:00:00Z",
    });

    const user = userEvent.setup();
    render(<SignupPage />);
    await fillValidForm(user)();

    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(mockSignup).toHaveBeenCalledWith({
        first_name: "Alex",
        last_name: "Smith",
        email: "alex@school.edu",
        school_name: "Test High School",
        password: "SecurePass1",
      });
    });

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith(
        expect.stringContaining("/signup/verify"),
      );
    });
  });
});

// ---------------------------------------------------------------------------
// Server error handling
// ---------------------------------------------------------------------------

describe("SignupPage — server errors", () => {
  it("shows user-safe message on 409 conflict", async () => {
    mockSignup.mockRejectedValueOnce(
      new ApiError(409, { code: "CONFLICT", message: "Email taken." }),
    );

    const user = userEvent.setup();
    render(<SignupPage />);
    await fillValidForm(user)();
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/account with this email already exists/i),
      ).toBeInTheDocument();
    });
    // No raw API error detail exposed
    expect(screen.queryByText("Email taken.")).not.toBeInTheDocument();
  });

  it("shows user-safe message on 429 rate limit", async () => {
    mockSignup.mockRejectedValueOnce(
      new ApiError(429, { code: "RATE_LIMITED", message: "Too many requests." }),
    );

    const user = userEvent.setup();
    render(<SignupPage />);
    await fillValidForm(user)();
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/too many sign-up attempts/i)).toBeInTheDocument();
    });
  });

  it("shows generic error for unexpected server error", async () => {
    mockSignup.mockRejectedValueOnce(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server exploded." }),
    );

    const user = userEvent.setup();
    render(<SignupPage />);
    await fillValidForm(user)();
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(/sign-up failed/i)).toBeInTheDocument();
    });
    // Raw server error never shown to user
    expect(screen.queryByText("Server exploded.")).not.toBeInTheDocument();
  });
});
