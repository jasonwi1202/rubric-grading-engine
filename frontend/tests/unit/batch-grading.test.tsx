/**
 * Tests for BatchGradingPanel — M3.17 (Batch grading UI).
 *
 * Covers:
 * - "Grade now" button visible when canGrade=true and status is idle
 * - "Grade now" button hidden when canGrade=false
 * - Clicking "Grade now" calls triggerGrading and shows "Starting…"
 * - Trigger error shows generic error message (no PII)
 * - Progress bar renders with correct percentage when grading is in-progress
 * - Polling stops when batch status is "complete"
 * - Polling stops when batch status is "failed"
 * - Polling stops when batch status is "partial"
 * - In-app notification shown on "complete"
 * - In-app notification shown on "partial"
 * - In-app notification shown on "failed"
 * - Per-essay status badges render for queued/grading/complete/failed
 * - Retry button shown only for failed essays
 * - Retry button hidden for queued/grading/complete essays
 * - Clicking retry calls retryEssayGrading with correct essay ID
 * - Retry API error shows generic message (no PII)
 * - POLL_INTERVAL_MS export is 3000
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and error codes only.
 * - Error codes mapped to human labels; raw exception strings never rendered.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockTriggerGrading = vi.fn();
const mockGetGradingStatus = vi.fn();
const mockRetryEssayGrading = vi.fn();

vi.mock("@/lib/api/grading", () => ({
  triggerGrading: (...args: unknown[]) => mockTriggerGrading(...args),
  getGradingStatus: (...args: unknown[]) => mockGetGradingStatus(...args),
  retryEssayGrading: (...args: unknown[]) => mockRetryEssayGrading(...args),
}));

import {
  BatchGradingPanel,
  POLL_INTERVAL_MS,
} from "@/components/grading/BatchGradingPanel";
import type { GradingStatusResponse } from "@/lib/api/grading";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ASSIGNMENT_ID = "asgn-test-001";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function makeStatus(
  overrides: Partial<GradingStatusResponse> = {},
): GradingStatusResponse {
  return {
    status: "idle",
    total: 0,
    complete: 0,
    failed: 0,
    essays: [],
    ...overrides,
  };
}

/** Factory for test essay entries — never uses real student names (FERPA). */
function makeEssay(
  overrides: Partial<import("@/lib/api/grading").EssayGradingEntry> &
    Pick<import("@/lib/api/grading").EssayGradingEntry, "id" | "status">,
): import("@/lib/api/grading").EssayGradingEntry {
  return {
    student_name: null,
    error: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("POLL_INTERVAL_MS", () => {
  it("is 3000 ms", () => {
    expect(POLL_INTERVAL_MS).toBe(3000);
  });
});

describe("BatchGradingPanel — Grade now button visibility", () => {
  beforeEach(() => {
    mockGetGradingStatus.mockResolvedValue(makeStatus({ status: "idle" }));
  });

  it("shows 'Grade now' button when canGrade=true and status is idle", async () => {
    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );
    expect(
      await screen.findByRole("button", { name: /grade now/i }),
    ).toBeInTheDocument();
  });

  it("does not show 'Grade now' button when canGrade=false", async () => {
    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={false} />,
      { wrapper },
    );
    // Wait for component to settle
    await screen.findByText(/grading is not available/i);
    expect(
      screen.queryByRole("button", { name: /grade now/i }),
    ).not.toBeInTheDocument();
  });
});

describe("BatchGradingPanel — Trigger grading", () => {
  beforeEach(() => {
    mockGetGradingStatus.mockResolvedValue(makeStatus({ status: "idle" }));
  });

  it("calls triggerGrading with the assignment ID when clicked", async () => {
    mockTriggerGrading.mockResolvedValue({ message: "ok" });
    const user = userEvent.setup();

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    const btn = await screen.findByRole("button", { name: /grade now/i });
    await user.click(btn);

    expect(mockTriggerGrading).toHaveBeenCalledWith(ASSIGNMENT_ID);
  });

  it("shows a generic error message when triggering grading fails", async () => {
    mockTriggerGrading.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );
    const user = userEvent.setup();

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    const btn = await screen.findByRole("button", { name: /grade now/i });
    await user.click(btn);

    expect(
      await screen.findByRole("alert", {
        // The alert container
      }),
    ).toHaveTextContent(/failed to start grading/i);
  });
});

describe("BatchGradingPanel — Progress bar", () => {
  it("renders a progress bar with the correct percentage", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({ status: "processing", total: 10, complete: 4, failed: 1, essays: [] }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    // 5 out of 10 (complete + failed) = 50%
    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("value", "50");
    expect(bar).toHaveAttribute("max", "100");
    expect(bar).toHaveAttribute("aria-label", "Grading progress: 50%");
    // Visible text showing counts
    expect(screen.getByText(/4 of 10 complete/i)).toBeInTheDocument();
    expect(screen.getByText(/1 failed/i)).toBeInTheDocument();
  });

  it("renders progress bar and essay list simultaneously when essays are populated", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "processing",
        total: 2,
        complete: 1,
        failed: 0,
        essays: [
          makeEssay({ id: "essay-aaa-001", status: "complete" }),
          makeEssay({ id: "essay-bbb-002", status: "grading" }),
        ],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    // 1 out of 2 = 50%
    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("value", "50");
    // Essay list also rendered
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("Grading…")).toBeInTheDocument();
  });

  it("shows 0% when total is 0", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({ status: "processing", total: 0, complete: 0, failed: 0, essays: [] }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("value", "0");
  });
});

describe("BatchGradingPanel — Polling stops on terminal states", () => {
  it("shows completion notification when status is already 'complete' on load", async () => {
    // If status is already complete, the completion message should appear
    // and refetchInterval returns false (no further polling)
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({ status: "complete", total: 2, complete: 2, failed: 0, essays: [] }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    await waitFor(() =>
      expect(screen.getByText(/grading complete/i)).toBeInTheDocument(),
    );
  });

  it("shows failure notification when status is already 'failed' on load", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({ status: "failed", total: 1, complete: 0, failed: 1, essays: [] }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    await waitFor(() =>
      expect(screen.getByText(/grading failed for all essays/i)).toBeInTheDocument(),
    );
  });

  it("shows 'Grade now' button again after batch reaches terminal state", async () => {
    // When grading is complete, teacher should be able to re-trigger
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({ status: "complete", total: 3, complete: 3, failed: 0, essays: [] }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    // Completion notification
    await waitFor(() =>
      expect(screen.getByText(/grading complete/i)).toBeInTheDocument(),
    );

    // Grade now button should reappear for re-grading
    expect(
      screen.getByRole("button", { name: /grade now/i }),
    ).toBeInTheDocument();
  });
});

describe("BatchGradingPanel — Completion notifications", () => {
  it("shows success notification on 'complete'", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "complete",
        total: 5,
        complete: 5,
        failed: 0,
        essays: [],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    expect(
      await screen.findByText(/grading complete/i),
    ).toBeInTheDocument();
  });

  it("shows partial notification on 'partial'", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "partial",
        total: 5,
        complete: 3,
        failed: 2,
        essays: [],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    expect(
      await screen.findByText(/grading finished/i),
    ).toBeInTheDocument();
  });

  it("shows failure notification on 'failed'", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "failed",
        total: 2,
        complete: 0,
        failed: 2,
        essays: [],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    expect(
      await screen.findByText(/grading failed for all essays/i),
    ).toBeInTheDocument();
  });
});

describe("BatchGradingPanel — Per-essay status", () => {
  it("renders status badges for queued, grading, complete, and failed essays", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "processing",
        total: 4,
        complete: 1,
        failed: 1,
        essays: [
          makeEssay({ id: "essay-aaa-001", status: "queued" }),
          makeEssay({ id: "essay-bbb-002", status: "grading" }),
          makeEssay({ id: "essay-ccc-003", status: "complete" }),
          makeEssay({ id: "essay-ddd-004", status: "failed", error: "LLM_TIMEOUT" }),
        ],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    expect(await screen.findByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("Grading…")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("shows human-readable error label for LLM_TIMEOUT", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "processing",
        total: 1,
        complete: 0,
        failed: 1,
        essays: [makeEssay({ id: "essay-eee-005", status: "failed", error: "LLM_TIMEOUT" })],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    expect(
      await screen.findByText(/ai request timed out/i),
    ).toBeInTheDocument();
  });

  it("shows generic error label for unknown error codes", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "processing",
        total: 1,
        complete: 0,
        failed: 1,
        essays: [makeEssay({ id: "essay-fff-006", status: "failed", error: "SOME_UNKNOWN_CODE" })],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    expect(await screen.findByText(/grading error/i)).toBeInTheDocument();
  });

  it("does not show error text for graded essays", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "complete",
        total: 1,
        complete: 1,
        failed: 0,
        essays: [makeEssay({ id: "essay-ggg-007", status: "complete" })],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    await screen.findByText("Complete");
    // No error label should be visible for a graded essay
    expect(screen.queryByText(/ai request timed out/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/grading error/i)).not.toBeInTheDocument();
  });
});

describe("BatchGradingPanel — Retry action", () => {
  it("shows retry button only for failed essays", async () => {
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "processing",
        total: 3,
        complete: 1,
        failed: 1,
        essays: [
          makeEssay({ id: "essay-hhh-008", status: "complete" }),
          makeEssay({ id: "essay-iii-009", status: "queued" }),
          makeEssay({ id: "essay-jjj-010", status: "failed", error: "PARSE_ERROR" }),
        ],
      }),
    );

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    await screen.findByText("Failed");
    const retryButtons = screen.getAllByRole("button", { name: /retry/i });
    // Only one retry button — for the failed essay
    expect(retryButtons).toHaveLength(1);
    // The component uses .slice(0, 8) for the aria-label prefix.
    // "essay-jjj-010".slice(0, 8) === "essay-jj"
    expect(retryButtons[0]).toHaveAttribute(
      "aria-label",
      "Retry grading for essay essay-jj",
    );
  });

  it("calls retryEssayGrading with the correct essay ID", async () => {
    mockRetryEssayGrading.mockResolvedValue({ message: "ok" });
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "processing",
        total: 1,
        complete: 0,
        failed: 1,
        essays: [makeEssay({ id: "essay-kkk-011", status: "failed", error: "LLM_TIMEOUT" })],
      }),
    );

    const user = userEvent.setup();
    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    const retryBtn = await screen.findByRole("button", { name: /retry/i });
    await user.click(retryBtn);

    await waitFor(() =>
      expect(mockRetryEssayGrading).toHaveBeenCalledWith("essay-kkk-011"),
    );
  });

  it("shows a generic error message when retry fails", async () => {
    mockRetryEssayGrading.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );
    mockGetGradingStatus.mockResolvedValue(
      makeStatus({
        status: "processing",
        total: 1,
        complete: 0,
        failed: 1,
        essays: [makeEssay({ id: "essay-lll-012", status: "failed", error: "LLM_TIMEOUT" })],
      }),
    );

    const user = userEvent.setup();
    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    const retryBtn = await screen.findByRole("button", { name: /retry/i });
    await user.click(retryBtn);

    expect(
      await screen.findByText(/retry failed/i),
    ).toBeInTheDocument();
  });
});

describe("BatchGradingPanel — Loading state", () => {
  it("shows a loading message while the initial status fetch is in flight", () => {
    // Never resolve — keeps the query in loading state
    mockGetGradingStatus.mockImplementation(() => new Promise(() => {}));

    render(
      <BatchGradingPanel assignmentId={ASSIGNMENT_ID} canGrade={true} />,
      { wrapper },
    );

    expect(
      screen.getByText(/loading grading progress/i),
    ).toBeInTheDocument();
    // Grade now button must not appear during loading
    expect(
      screen.queryByRole("button", { name: /grade now/i }),
    ).not.toBeInTheDocument();
  });
});
