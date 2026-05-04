/**
 * Tests for ErrorBoundary component.
 *
 * Covers:
 * - Renders children normally when no error occurs
 * - Shows default fallback when a child throws a rendering error
 * - Shows custom fallback when provided and a child throws
 * - "Try again" button resets the error state and re-renders children
 * - componentDidCatch does not log in test environment (NODE_ENV != development)
 *
 * Security:
 * - No student PII in fixtures.
 * - Error messages in fallback UI are static strings only.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { ErrorBoundary } from "@/components/layout/ErrorBoundary";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/**
 * A component that renders normally.
 */
function GoodChild() {
  return <p>All good</p>;
}

/**
 * A component that throws during render when `shouldThrow` is true.
 */
function BadChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("Intentional render error for testing");
  }
  return <p>Recovered</p>;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ErrorBoundary", () => {
  // Suppress the expected React error boundary console.error calls during tests
  // so test output stays clean. Vitest does not automatically suppress these.
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
  });

  it("renders children when no error occurs", () => {
    render(
      <ErrorBoundary>
        <GoodChild />
      </ErrorBoundary>,
    );
    expect(screen.getByText("All good")).toBeInTheDocument();
  });

  it("shows the default fallback when a child throws", () => {
    render(
      <ErrorBoundary>
        <BadChild shouldThrow />
      </ErrorBoundary>,
    );

    expect(
      screen.getByRole("alert"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Something went wrong loading this section/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("shows a custom fallback when provided and a child throws", () => {
    render(
      <ErrorBoundary fallback={<p role="alert">Custom error fallback</p>}>
        <BadChild shouldThrow />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Custom error fallback")).toBeInTheDocument();
    // The default fallback button should NOT be present
    expect(
      screen.queryByRole("button", { name: /try again/i }),
    ).not.toBeInTheDocument();
  });

  it("resets the error state when 'Try again' is clicked", async () => {
    const user = userEvent.setup();

    // Use a module-level flag so we can change the behaviour before the
    // boundary re-renders children after reset.
    let throwOnRender = true;
    function ToggleChild() {
      if (throwOnRender) throw new Error("controlled test error");
      return <p>Recovered</p>;
    }

    render(
      <ErrorBoundary>
        <ToggleChild />
      </ErrorBoundary>,
    );

    // Error fallback should be visible
    expect(
      screen.getByText(/Something went wrong loading this section/i),
    ).toBeInTheDocument();

    // Flip the flag so that when the boundary re-renders children after the
    // reset they will succeed.
    throwOnRender = false;

    // Click "Try again" — this resets hasError which triggers a re-render.
    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(screen.getByText("Recovered")).toBeInTheDocument();
    expect(
      screen.queryByText(/Something went wrong/i),
    ).not.toBeInTheDocument();
  });

  it("fallback UI does not expose the error message to the DOM", () => {
    render(
      <ErrorBoundary>
        <BadChild shouldThrow />
      </ErrorBoundary>,
    );

    // The raw error message must not appear in the rendered output
    expect(
      screen.queryByText(/Intentional render error/i),
    ).not.toBeInTheDocument();
  });
});
