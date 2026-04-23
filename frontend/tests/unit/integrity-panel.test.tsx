/**
 * Tests for IntegrityPanel — M4.6 (Integrity report API and UI).
 *
 * Covers:
 * - Panel renders with AI likelihood, similarity score, and flagged passages
 * - AI likelihood indicator shows correct label (low / moderate / high signal)
 * - Similarity score renders as a percentage
 * - Flagged passages list renders when passages are present
 * - "Mark as reviewed — no concern" button calls updateIntegrityStatus with "reviewed_clear"
 * - "Flag for follow-up" button calls updateIntegrityStatus with "flagged"
 * - "Mark as reviewed" button is disabled when status is already "reviewed_clear"
 * - "Flag for follow-up" button is disabled when status is already "flagged"
 * - Error message shown on status mutation failure (static string, no PII)
 * - onStatusUpdate callback is called after a successful status update
 * - IntegrityPanelEmpty renders when no report is available
 * - IntegrityPanelSkeleton renders loading state
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and synthetic text only.
 * - Error assertions verify static UI strings, not raw server messages.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — must come before component imports
// ---------------------------------------------------------------------------

const mockUpdateIntegrityStatus = vi.fn();

vi.mock("@/lib/api/integrity", () => ({
  updateIntegrityStatus: (...args: unknown[]) =>
    mockUpdateIntegrityStatus(...args),
  getIntegrityReport: vi.fn(),
  getIntegritySummary: vi.fn(),
}));

import {
  IntegrityPanel,
  IntegrityPanelEmpty,
  IntegrityPanelSkeleton,
} from "@/components/grading/IntegrityPanel";
import type { IntegrityReportResponse } from "@/lib/api/integrity";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Factory for an IntegrityReportResponse. No real student data. */
function makeReport(
  overrides: Partial<IntegrityReportResponse> = {},
): IntegrityReportResponse {
  return {
    id: "report-test-001",
    essay_id: "essay-test-001",
    essay_version_id: "ev-test-001",
    provider: "internal",
    ai_likelihood: 0.25,
    similarity_score: 0.1,
    flagged_passages: [],
    status: "pending",
    reviewed_at: null,
    created_at: "2026-04-23T00:00:00Z",
    updated_at: "2026-04-23T00:00:00Z",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// IntegrityPanel — rendering
// ---------------------------------------------------------------------------

describe("IntegrityPanel — renders integrity signals", () => {
  beforeEach(() => {
    mockUpdateIntegrityStatus.mockReset();
  });

  it("renders the panel heading", () => {
    render(<IntegrityPanel report={makeReport()} />, { wrapper });
    expect(
      screen.getByRole("region", { name: /academic integrity signals/i }),
    ).toBeInTheDocument();
  });

  it("renders the AI likelihood as a percentage", () => {
    render(<IntegrityPanel report={makeReport({ ai_likelihood: 0.73 })} />, {
      wrapper,
    });
    expect(screen.getByText("73%")).toBeInTheDocument();
  });

  it("shows 'Low signal' for ai_likelihood < 0.3", () => {
    render(<IntegrityPanel report={makeReport({ ai_likelihood: 0.1 })} />, {
      wrapper,
    });
    expect(screen.getByText("Low signal")).toBeInTheDocument();
  });

  it("shows 'Moderate signal' for ai_likelihood between 0.3 and 0.7", () => {
    render(<IntegrityPanel report={makeReport({ ai_likelihood: 0.5 })} />, {
      wrapper,
    });
    expect(screen.getByText("Moderate signal")).toBeInTheDocument();
  });

  it("shows 'High signal' for ai_likelihood >= 0.7", () => {
    render(<IntegrityPanel report={makeReport({ ai_likelihood: 0.85 })} />, {
      wrapper,
    });
    expect(screen.getByText("High signal")).toBeInTheDocument();
  });

  it("renders 'Not available' when ai_likelihood is null", () => {
    render(<IntegrityPanel report={makeReport({ ai_likelihood: null })} />, {
      wrapper,
    });
    expect(screen.getByText("Not available")).toBeInTheDocument();
  });

  it("renders the similarity score as a percentage", () => {
    render(
      <IntegrityPanel report={makeReport({ similarity_score: 0.42 })} />,
      { wrapper },
    );
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("renders '—' for null similarity score", () => {
    render(
      <IntegrityPanel report={makeReport({ similarity_score: null })} />,
      { wrapper },
    );
    // The similarity row value should be "—"
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders flagged passage text when passages are present", () => {
    const report = makeReport({
      flagged_passages: [
        { text: "Synthetic flagged text for testing.", ai_probability: 0.9 },
      ],
    });
    render(<IntegrityPanel report={report} />, { wrapper });
    expect(
      screen.getByText(/Synthetic flagged text for testing\./),
    ).toBeInTheDocument();
  });

  it("does not render flagged passages list when passages array is empty", () => {
    render(<IntegrityPanel report={makeReport({ flagged_passages: [] })} />, {
      wrapper,
    });
    expect(
      screen.queryByRole("list", { name: /flagged passages/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the current status badge", () => {
    render(<IntegrityPanel report={makeReport({ status: "flagged" })} />, {
      wrapper,
    });
    expect(screen.getByText("Flagged for follow-up")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// IntegrityPanel — status actions
// ---------------------------------------------------------------------------

describe("IntegrityPanel — status actions", () => {
  beforeEach(() => {
    mockUpdateIntegrityStatus.mockReset();
  });

  it("calls updateIntegrityStatus with 'reviewed_clear' when the reviewed button is clicked", async () => {
    const user = userEvent.setup();
    const updatedReport = makeReport({ status: "reviewed_clear" });
    mockUpdateIntegrityStatus.mockResolvedValueOnce(updatedReport);

    render(<IntegrityPanel report={makeReport()} />, { wrapper });

    const btn = screen.getByRole("button", {
      name: /mark as reviewed.*no concern/i,
    });
    await user.click(btn);

    await waitFor(() => {
      expect(mockUpdateIntegrityStatus).toHaveBeenCalledWith("report-test-001", {
        status: "reviewed_clear",
      });
    });
  });

  it("calls updateIntegrityStatus with 'flagged' when the flag button is clicked", async () => {
    const user = userEvent.setup();
    const updatedReport = makeReport({ status: "flagged" });
    mockUpdateIntegrityStatus.mockResolvedValueOnce(updatedReport);

    render(<IntegrityPanel report={makeReport()} />, { wrapper });

    const btn = screen.getByRole("button", { name: /flag for follow-up/i });
    await user.click(btn);

    await waitFor(() => {
      expect(mockUpdateIntegrityStatus).toHaveBeenCalledWith("report-test-001", {
        status: "flagged",
      });
    });
  });

  it("disables 'Mark as reviewed' button when status is already 'reviewed_clear'", () => {
    render(
      <IntegrityPanel report={makeReport({ status: "reviewed_clear" })} />,
      { wrapper },
    );
    const btn = screen.getByRole("button", {
      name: /mark as reviewed.*no concern/i,
    });
    expect(btn).toBeDisabled();
  });

  it("disables 'Flag for follow-up' button when status is already 'flagged'", () => {
    render(
      <IntegrityPanel report={makeReport({ status: "flagged" })} />,
      { wrapper },
    );
    const btn = screen.getByRole("button", { name: /flag for follow-up/i });
    expect(btn).toBeDisabled();
  });

  it("calls onStatusUpdate callback with updated report on success", async () => {
    const user = userEvent.setup();
    const updatedReport = makeReport({ status: "reviewed_clear" });
    mockUpdateIntegrityStatus.mockResolvedValueOnce(updatedReport);
    const onStatusUpdate = vi.fn();

    render(
      <IntegrityPanel report={makeReport()} onStatusUpdate={onStatusUpdate} />,
      { wrapper },
    );

    const btn = screen.getByRole("button", {
      name: /mark as reviewed.*no concern/i,
    });
    await user.click(btn);

    await waitFor(() => {
      expect(onStatusUpdate).toHaveBeenCalledWith(updatedReport);
    });
  });

  it("shows a static error message on status mutation failure", async () => {
    const user = userEvent.setup();
    mockUpdateIntegrityStatus.mockRejectedValueOnce(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "An unexpected error occurred." }),
    );

    render(<IntegrityPanel report={makeReport()} />, { wrapper });

    const btn = screen.getByRole("button", { name: /flag for follow-up/i });
    await user.click(btn);

    await waitFor(() => {
      expect(
        screen.getByRole("alert"),
      ).toHaveTextContent("Failed to update status. Please try again.");
    });

    // Verify no raw server text is exposed
    expect(screen.queryByText(/unexpected error/i)).not.toBeInTheDocument();
  });

  it("shows a 'not found' static error when the API returns NOT_FOUND", async () => {
    const user = userEvent.setup();
    mockUpdateIntegrityStatus.mockRejectedValueOnce(
      new ApiError(404, { code: "NOT_FOUND", message: "Integrity report not found." }),
    );

    render(<IntegrityPanel report={makeReport()} />, { wrapper });

    await user.click(
      screen.getByRole("button", { name: /mark as reviewed.*no concern/i }),
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Integrity report not found. Please refresh the page.",
      );
    });
  });
});

// ---------------------------------------------------------------------------
// IntegrityPanelEmpty
// ---------------------------------------------------------------------------

describe("IntegrityPanelEmpty", () => {
  it("renders the 'no report' message", () => {
    render(<IntegrityPanelEmpty />, { wrapper });
    expect(
      screen.getByText(/no integrity report is available/i),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// IntegrityPanelSkeleton
// ---------------------------------------------------------------------------

describe("IntegrityPanelSkeleton", () => {
  it("renders loading state with aria-busy", () => {
    render(<IntegrityPanelSkeleton />, { wrapper });
    expect(
      screen.getByRole("region", { name: /loading integrity signals/i }),
    ).toHaveAttribute("aria-busy", "true");
  });
});
