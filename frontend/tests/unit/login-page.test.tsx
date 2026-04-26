/**
 * Tests for the /login page redirect behavior.
 *
 * Covers:
 * - Successful sign-in without a `next` query parameter redirects to /dashboard.
 * - Successful sign-in with a safe `next` query parameter redirects to that path.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

const mockReplace = vi.fn();
const mockSearchParamsGet = vi.fn<(
  key: string,
) => string | null>();
const mockLogin = vi.fn<
  (email: string, password: string) => Promise<{ access_token: string; token_type: string }>
>();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => ({ get: mockSearchParamsGet }),
}));

vi.mock("@/lib/auth/session", () => ({
  login: (...args: [string, string]) => mockLogin(...args),
}));

import LoginPage from "@/app/(auth)/login/page";

beforeEach(() => {
  vi.clearAllMocks();
  mockLogin.mockResolvedValue({
    access_token: "test-token",
    token_type: "bearer",
  });
});

describe("LoginPage — redirect behavior", () => {
  it("redirects to /dashboard when next is missing", async () => {
    mockSearchParamsGet.mockReturnValue(null);

    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(screen.getByLabelText(/email/i), "teacher@example.com");
    await user.type(screen.getByLabelText(/password/i), "TestPass123!");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("teacher@example.com", "TestPass123!");
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("redirects to safe next path when provided", async () => {
    mockSearchParamsGet.mockImplementation((key: string) =>
      key === "next" ? "/dashboard/classes" : null,
    );

    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(screen.getByLabelText(/email/i), "teacher@example.com");
    await user.type(screen.getByLabelText(/password/i), "TestPass123!");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard/classes");
    });
  });
});
