/**
 * Tests for ErrorBoundary component.
 *
 * Covers:
 * - Renders children normally when no error occurs
 * - Shows default fallback when a child throws a rendering error
 * - Shows custom static fallback (`fallback` prop) when provided and a child throws
 * - `fallbackRender` prop receives `resetErrorBoundary` and can trigger a reset
 * - "Try again" button on the default fallback resets the error state and re-renders children
 * - componentDidCatch does not log the [ErrorBoundary] prefix outside development (NODE_ENV !== "development")
 * - Fallback UI does not expose the raw error message to the DOM
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

  it("shows a custom static fallback when provided and a child throws", () => {
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

  it("fallbackRender receives resetErrorBoundary and can reset the boundary", async () => {
    const user = userEvent.setup();
    let throwOnRender = true;

    function ToggleChild() {
      if (throwOnRender) throw new Error("controlled test error for render prop");
      return <p>Render-prop recovered</p>;
    }

    render(
      <ErrorBoundary
        fallbackRender={({ resetErrorBoundary }) => (
          <div role="alert">
            <p>Custom render-prop fallback</p>
            <button type="button" onClick={resetErrorBoundary}>
              Reset via render prop
            </button>
          </div>
        )}
      >
        <ToggleChild />
      </ErrorBoundary>,
    );

    // Custom fallback should appear
    expect(screen.getByText("Custom render-prop fallback")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /reset via render prop/i }),
    ).toBeInTheDocument();

    // Allow subsequent render to succeed
    throwOnRender = false;

    await user.click(
      screen.getByRole("button", { name: /reset via render prop/i }),
    );

    expect(screen.getByText("Render-prop recovered")).toBeInTheDocument();
    expect(
      screen.queryByText("Custom render-prop fallback"),
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

  it("does not log the [ErrorBoundary] prefix outside development environments", () => {
    // NODE_ENV in the test runner is "test", not "development", so componentDidCatch
    // must not emit the [ErrorBoundary] log line.
    render(
      <ErrorBoundary>
        <BadChild shouldThrow />
      </ErrorBoundary>,
    );

    const boundaryLogCalls = consoleError.mock.calls.filter(
      (args: unknown[]) => typeof args[0] === "string" && args[0].includes("[ErrorBoundary]"),
    );
    expect(boundaryLogCalls).toHaveLength(0);
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
