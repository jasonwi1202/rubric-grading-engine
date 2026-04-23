/**
 * Tests for ExportPanel and buildClipboardText — M3.26 (Export UI).
 *
 * Covers:
 * - "Export" button renders in the assignment page action area
 * - PDF export option is disabled when hasLockedGrades=false
 * - CSV export option is disabled when hasLockedGrades=false
 * - PDF export option is enabled when hasLockedGrades=true
 * - CSV export option is enabled when hasLockedGrades=true
 * - Clicking "Export" opens the dropdown menu
 * - Clicking "Export feedback as PDF ZIP" calls startExport when enabled
 * - Clicking "Export grades as CSV" calls downloadGradesCsv when enabled
 * - Disabled reason message shown when no locked grades
 * - PDF export in-progress shows "Export in progress…"
 * - PDF export failure shows error message (no PII)
 * - CSV export failure shows error message (no PII)
 * - buildClipboardText: formats overall feedback
 * - buildClipboardText: formats per-criterion scores and feedback
 * - buildClipboardText: handles missing criterion metadata gracefully
 * - buildClipboardText: handles no criteria scores
 * - EXPORT_POLL_INTERVAL_MS is 3000
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and placeholder text only.
 * - No credential-format strings in test data.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockStartExport = vi.fn();
const mockGetExportStatus = vi.fn();
const mockGetExportDownloadUrl = vi.fn();
const mockDownloadGradesCsv = vi.fn();

vi.mock("@/lib/api/exports", () => ({
  startExport: (...args: unknown[]) => mockStartExport(...args),
  getExportStatus: (...args: unknown[]) => mockGetExportStatus(...args),
  getExportDownloadUrl: (...args: unknown[]) =>
    mockGetExportDownloadUrl(...args),
  downloadGradesCsv: (...args: unknown[]) => mockDownloadGradesCsv(...args),
}));

// ---------------------------------------------------------------------------
// Imports (after mocks)
// ---------------------------------------------------------------------------

import {
  ExportPanel,
  EXPORT_POLL_INTERVAL_MS,
} from "@/components/grading/ExportPanel";

import { buildClipboardText } from "@/components/grading/EssayReviewPanel";
import type { GradeResponse } from "@/lib/api/grades";
import type { RubricSnapshotCriterion } from "@/components/grading/EssayReviewPanel";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ASSIGNMENT_ID = "asgn-export-001";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ---------------------------------------------------------------------------
// EXPORT_POLL_INTERVAL_MS
// ---------------------------------------------------------------------------

describe("EXPORT_POLL_INTERVAL_MS", () => {
  it("is 3000 ms", () => {
    expect(EXPORT_POLL_INTERVAL_MS).toBe(3000);
  });
});

// ---------------------------------------------------------------------------
// ExportPanel — button rendering
// ---------------------------------------------------------------------------

describe("ExportPanel — Export button", () => {
  it("renders an Export button", () => {
    render(
      <ExportPanel
        assignmentId={ASSIGNMENT_ID}
        hasLockedGrades={false}
      />,
      { wrapper },
    );
    expect(
      screen.getByRole("button", { name: /export options/i }),
    ).toBeInTheDocument();
  });

  it("does not show the menu before the button is clicked", () => {
    render(
      <ExportPanel
        assignmentId={ASSIGNMENT_ID}
        hasLockedGrades={false}
      />,
      { wrapper },
    );
    expect(screen.queryByTestId("export-panel-menu")).not.toBeInTheDocument();
  });

  it("opens the dropdown menu when clicked", async () => {
    const user = userEvent.setup();
    render(
      <ExportPanel
        assignmentId={ASSIGNMENT_ID}
        hasLockedGrades={false}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("button", { name: /export options/i }));
    expect(screen.getByTestId("export-panel-menu")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// ExportPanel — disabled state when no locked grades
// ---------------------------------------------------------------------------

describe("ExportPanel — disabled when no locked grades", () => {
  beforeEach(async () => {
    const user = userEvent.setup();
    render(
      <ExportPanel
        assignmentId={ASSIGNMENT_ID}
        hasLockedGrades={false}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("button", { name: /export options/i }));
  });

  it("shows a disabled-reason message", () => {
    expect(
      screen.getByText(/lock at least one grade/i),
    ).toBeInTheDocument();
  });

  it("PDF export menu item is disabled", () => {
    const pdfItem = screen.getByRole("button", {
      name: /export feedback as pdf zip/i,
    });
    expect(pdfItem).toBeDisabled();
  });

  it("CSV export menu item is disabled", () => {
    const csvItem = screen.getByRole("button", {
      name: /export grades as csv/i,
    });
    expect(csvItem).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// ExportPanel — enabled state with locked grades
// ---------------------------------------------------------------------------

describe("ExportPanel — enabled when has locked grades", () => {
  beforeEach(async () => {
    const user = userEvent.setup();
    render(
      <ExportPanel
        assignmentId={ASSIGNMENT_ID}
        hasLockedGrades={true}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("button", { name: /export options/i }));
  });

  it("does not show the disabled-reason message", () => {
    expect(screen.queryByText(/lock at least one grade/i)).not.toBeInTheDocument();
  });

  it("PDF export menu item is enabled", () => {
    const pdfItem = screen.getByRole("button", {
      name: /export feedback as pdf zip/i,
    });
    expect(pdfItem).not.toBeDisabled();
  });

  it("CSV export menu item is enabled", () => {
    const csvItem = screen.getByRole("button", {
      name: /export grades as csv/i,
    });
    expect(csvItem).not.toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// ExportPanel — PDF export flow
// ---------------------------------------------------------------------------

describe("ExportPanel — PDF export", () => {
  it("calls startExport with the assignment ID when PDF item is clicked", async () => {
    mockStartExport.mockResolvedValue({ task_id: "task-pdf-001", assignment_id: ASSIGNMENT_ID, status: "pending" });
    mockGetExportStatus.mockResolvedValue({
      task_id: "task-pdf-001",
      status: "pending",
      total: 0,
      complete: 0,
      error: null,
    });

    const user = userEvent.setup();
    render(
      <ExportPanel assignmentId={ASSIGNMENT_ID} hasLockedGrades={true} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /export options/i }));
    const pdfItem = screen.getByRole("button", {
      name: /export feedback as pdf zip/i,
    });
    await user.click(pdfItem);

    await waitFor(() =>
      expect(mockStartExport).toHaveBeenCalledWith(ASSIGNMENT_ID),
    );
  });

  it("shows 'Export in progress…' while the export task is active", async () => {
    mockStartExport.mockResolvedValue({ task_id: "task-pdf-002", assignment_id: ASSIGNMENT_ID, status: "pending" });
    mockGetExportStatus.mockResolvedValue({
      task_id: "task-pdf-002",
      status: "processing",
      total: 10,
      complete: 4,
      error: null,
    });

    const user = userEvent.setup();
    render(
      <ExportPanel assignmentId={ASSIGNMENT_ID} hasLockedGrades={true} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /export options/i }));
    await user.click(
      screen.getByRole("button", { name: /export feedback as pdf zip/i }),
    );

    await waitFor(() =>
      expect(screen.getByText(/export in progress/i)).toBeInTheDocument(),
    );
  });

  it("shows download link when export is complete", async () => {
    mockStartExport.mockResolvedValue({ task_id: "task-pdf-003", assignment_id: ASSIGNMENT_ID, status: "pending" });
    mockGetExportStatus.mockResolvedValue({
      task_id: "task-pdf-003",
      status: "complete",
      total: 10,
      complete: 10,
      error: null,
    });
    mockGetExportDownloadUrl.mockResolvedValue({
      url: "https://s3.example.com/export-test-zip",
      expires_in_seconds: 900,
    });

    const user = userEvent.setup();
    render(
      <ExportPanel assignmentId={ASSIGNMENT_ID} hasLockedGrades={true} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /export options/i }));
    await user.click(
      screen.getByRole("button", { name: /export feedback as pdf zip/i }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("link", { name: /download the exported pdf zip file/i }),
      ).toBeInTheDocument(),
    );

    expect(
      screen.getByRole("link", { name: /download the exported pdf zip file/i }),
    ).toHaveAttribute("href", "https://s3.example.com/export-test-zip");
  });

  it("shows a generic error when startExport fails (no PII)", async () => {
    mockStartExport.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );

    const user = userEvent.setup();
    render(
      <ExportPanel assignmentId={ASSIGNMENT_ID} hasLockedGrades={true} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /export options/i }));
    await user.click(
      screen.getByRole("button", { name: /export feedback as pdf zip/i }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("alert"),
      ).toHaveTextContent(/failed to start export/i),
    );
  });
});

// ---------------------------------------------------------------------------
// ExportPanel — CSV export flow
// ---------------------------------------------------------------------------

describe("ExportPanel — CSV export", () => {
  it("calls downloadGradesCsv with the assignment ID when CSV item is clicked", async () => {
    mockDownloadGradesCsv.mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(
      <ExportPanel assignmentId={ASSIGNMENT_ID} hasLockedGrades={true} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /export options/i }));
    const csvItem = screen.getByRole("button", {
      name: /export grades as csv/i,
    });
    await user.click(csvItem);

    await waitFor(() =>
      expect(mockDownloadGradesCsv).toHaveBeenCalledWith(ASSIGNMENT_ID),
    );
  });

  it("shows a generic error when CSV download fails (no PII)", async () => {
    mockDownloadGradesCsv.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );

    const user = userEvent.setup();
    render(
      <ExportPanel assignmentId={ASSIGNMENT_ID} hasLockedGrades={true} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /export options/i }));
    await user.click(
      screen.getByRole("button", { name: /export grades as csv/i }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("alert"),
      ).toHaveTextContent(/failed to download grades/i),
    );
  });
});

// ---------------------------------------------------------------------------
// buildClipboardText — unit tests
// ---------------------------------------------------------------------------

/** Factory for a minimal GradeResponse (no PII in fixture values). */
function makeGrade(
  overrides: Partial<GradeResponse> = {},
): GradeResponse {
  return {
    id: "grade-clip-001",
    essay_version_id: "ev-clip-001",
    total_score: "7.00",
    max_possible_score: "10.00",
    summary_feedback: "Overall feedback text.",
    summary_feedback_edited: null,
    strictness: "balanced",
    ai_model: "test-model",
    prompt_version: "v1",
    is_locked: true,
    locked_at: "2026-04-01T00:00:00Z",
    overall_confidence: "high",
    created_at: "2026-04-01T00:00:00Z",
    criterion_scores: [],
    ...overrides,
  };
}

/** Factory for a RubricSnapshotCriterion. */
function makeCriterion(
  overrides: Partial<RubricSnapshotCriterion> &
    Pick<RubricSnapshotCriterion, "id" | "name">,
): RubricSnapshotCriterion {
  return {
    description: "Test criterion description",
    weight: 1,
    min_score: 0,
    max_score: 5,
    ...overrides,
  };
}

describe("buildClipboardText — overall feedback", () => {
  it("includes summary_feedback when summary_feedback_edited is null", () => {
    const grade = makeGrade({ summary_feedback: "AI feedback here." });
    const result = buildClipboardText(grade, []);
    expect(result).toContain("AI feedback here.");
  });

  it("prefers summary_feedback_edited over summary_feedback", () => {
    const grade = makeGrade({
      summary_feedback: "AI feedback here.",
      summary_feedback_edited: "Teacher edited feedback.",
    });
    const result = buildClipboardText(grade, []);
    expect(result).toContain("Teacher edited feedback.");
    expect(result).not.toContain("AI feedback here.");
  });

  it("includes 'Overall feedback:' heading", () => {
    const grade = makeGrade({ summary_feedback: "Some feedback." });
    const result = buildClipboardText(grade, []);
    expect(result).toContain("Overall feedback:");
  });

  it("handles empty summary_feedback gracefully", () => {
    const grade = makeGrade({ summary_feedback: "", summary_feedback_edited: null });
    const result = buildClipboardText(grade, []);
    // No heading for empty feedback
    expect(result).not.toContain("Overall feedback:");
  });
});

describe("buildClipboardText — per-criterion entries", () => {
  it("includes criterion name, score, and feedback", () => {
    const criterion = makeCriterion({ id: "crit-001", name: "Argument Quality" });
    const grade = makeGrade({
      summary_feedback: "Overall.",
      criterion_scores: [
        {
          id: "cs-001",
          rubric_criterion_id: "crit-001",
          ai_score: 3,
          teacher_score: 4,
          final_score: 4,
          ai_justification: "AI rationale.",
          ai_feedback: "AI feedback text.",
          teacher_feedback: "Teacher feedback text.",
          confidence: "high",
          created_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    const result = buildClipboardText(grade, [criterion]);
    expect(result).toContain("--- Argument Quality ---");
    expect(result).toContain("Score: 4 / 5");
    // Teacher feedback preferred over AI feedback
    expect(result).toContain("Teacher feedback text.");
    expect(result).not.toContain("AI feedback text.");
  });

  it("falls back to AI feedback when teacher_feedback is null", () => {
    const criterion = makeCriterion({ id: "crit-002", name: "Organisation" });
    const grade = makeGrade({
      summary_feedback: "Overall.",
      criterion_scores: [
        {
          id: "cs-002",
          rubric_criterion_id: "crit-002",
          ai_score: 3,
          teacher_score: null,
          final_score: 3,
          ai_justification: "AI rationale.",
          ai_feedback: "AI feedback only.",
          teacher_feedback: null,
          confidence: "medium",
          created_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    const result = buildClipboardText(grade, [criterion]);
    expect(result).toContain("AI feedback only.");
  });

  it("uses 'Criterion' placeholder when criterion metadata is not found", () => {
    const grade = makeGrade({
      summary_feedback: "Overall.",
      criterion_scores: [
        {
          id: "cs-003",
          rubric_criterion_id: "unknown-crit",
          ai_score: 2,
          teacher_score: null,
          final_score: 2,
          ai_justification: "AI rationale.",
          ai_feedback: null,
          teacher_feedback: null,
          confidence: "low",
          created_at: "2026-04-01T00:00:00Z",
        },
      ],
    });

    const result = buildClipboardText(grade, []);
    expect(result).toContain("--- Criterion ---");
  });

  it("returns only overall feedback when criterion_scores is empty", () => {
    const grade = makeGrade({
      summary_feedback: "Overall feedback.",
      criterion_scores: [],
    });
    const result = buildClipboardText(grade, []);
    expect(result).toBe("Overall feedback:\nOverall feedback.");
  });
});
