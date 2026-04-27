/**
 * Tests for M5.8 — Common Issues and Distribution UI.
 *
 * Covers:
 * - CommonIssuesPanel: shows empty state when no issues
 * - CommonIssuesPanel: renders ranked list of issues with skill name, counts, and bar
 * - CommonIssuesPanel: aria progressbar label includes skill name and average
 * - ScoreDistributionPanel: shows empty state when distributions is empty
 * - ScoreDistributionPanel: renders one histogram per skill
 * - ScoreDistributionPanel: outlier buckets (0–20% and 80–100%) receive amber ring
 * - ScoreDistributionPanel: non-outlier buckets do not receive amber ring
 * - TrendChart: shows placeholder when fewer than 2 completed assignments
 * - TrendChart: shows loading skeleton while queries are pending
 * - TrendChart: renders SVG with aria-label when 2+ completed assignments have data
 * - TrendChart: shows placeholder when all score data is null
 * - ClassInsightsPanel: shows loading skeleton while insights are loading
 * - ClassInsightsPanel: shows error alert when insights fetch fails
 * - ClassInsightsPanel: shows empty state when graded_essay_count is 0
 * - ClassInsightsPanel: renders Common Issues and Score Distributions sections
 * - ClassInsightsPanel: renders Trend section
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and placeholder names only.
 * - No credential-format strings in test data.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — declared before component imports per Vitest hoisting rules
// ---------------------------------------------------------------------------

const mockGetClassInsights = vi.fn();
const mockGetAssignmentAnalytics = vi.fn();

vi.mock("@/lib/api/classes", () => ({
  getClassInsights: (...args: unknown[]) => mockGetClassInsights(...args),
}));

vi.mock("@/lib/api/assignments", () => ({
  getAssignmentAnalytics: (...args: unknown[]) =>
    mockGetAssignmentAnalytics(...args),
}));

// ---------------------------------------------------------------------------
// Component imports (after mock declarations)
// ---------------------------------------------------------------------------

import { CommonIssuesPanel } from "@/components/classes/CommonIssuesPanel";
import { ScoreDistributionPanel } from "@/components/classes/ScoreDistributionPanel";
import { TrendChart } from "@/components/classes/TrendChart";
import { ClassInsightsPanel } from "@/components/classes/ClassInsightsPanel";
import { ApiError } from "@/lib/api/errors";
import type { CommonIssue, ScoreBucket } from "@/lib/api/classes";
import type { AssignmentListItem } from "@/lib/api/assignments";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const CLASS_ID = "cls-test-001";

function makeInsights(
  overrides: Partial<{
    graded_essay_count: number;
    student_count: number;
    skill_averages: Record<
      string,
      { avg_score: number; student_count: number; data_points: number }
    >;
    score_distributions: Record<string, ScoreBucket[]>;
    common_issues: CommonIssue[];
  }> = {},
) {
  return {
    class_id: CLASS_ID,
    assignment_count: 3,
    student_count: 10,
    graded_essay_count: 10,
    skill_averages: {
      evidence: { avg_score: 0.5, student_count: 10, data_points: 10 },
      thesis: { avg_score: 0.7, student_count: 10, data_points: 10 },
    },
    score_distributions: {
      evidence: [
        { label: "0-20%", count: 1 },
        { label: "20-40%", count: 3 },
        { label: "40-60%", count: 4 },
        { label: "60-80%", count: 2 },
        { label: "80-100%", count: 0 },
      ],
      thesis: [
        { label: "0-20%", count: 0 },
        { label: "20-40%", count: 1 },
        { label: "40-60%", count: 2 },
        { label: "60-80%", count: 4 },
        { label: "80-100%", count: 3 },
      ],
    },
    common_issues: [
      {
        skill_dimension: "evidence",
        avg_score: 0.5,
        affected_student_count: 4,
      },
    ],
    ...overrides,
  };
}

function makeAssignment(
  id: string,
  title: string,
  status: AssignmentListItem["status"] = "complete",
): AssignmentListItem {
  return {
    id,
    class_id: CLASS_ID,
    rubric_id: "rubric-001",
    title,
    prompt: null,
    due_date: null,
    status,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function makeAnalytics(
  assignmentId: string,
  overallScore: number | null = 0.72,
) {
  return {
    assignment_id: assignmentId,
    class_id: CLASS_ID,
    total_essay_count: 10,
    locked_essay_count: 10,
    overall_avg_normalized_score: overallScore,
    criterion_analytics: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// CommonIssuesPanel
// ---------------------------------------------------------------------------

describe("CommonIssuesPanel", () => {
  it("shows empty state when no issues", () => {
    render(<CommonIssuesPanel issues={[]} totalStudentCount={10} />, {
      wrapper,
    });
    expect(screen.getByText(/no common issues detected/i)).toBeInTheDocument();
  });

  it("renders ranked list of issues with skill name", () => {
    const issues: CommonIssue[] = [
      { skill_dimension: "evidence", avg_score: 0.45, affected_student_count: 6 },
      { skill_dimension: "thesis", avg_score: 0.52, affected_student_count: 3 },
    ];
    render(<CommonIssuesPanel issues={issues} totalStudentCount={10} />, {
      wrapper,
    });
    expect(screen.getByText(/evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/thesis/i)).toBeInTheDocument();
  });

  it("shows affected student count for each issue", () => {
    const issues: CommonIssue[] = [
      { skill_dimension: "evidence", avg_score: 0.45, affected_student_count: 6 },
    ];
    render(<CommonIssuesPanel issues={issues} totalStudentCount={10} />, {
      wrapper,
    });
    expect(screen.getByText(/6 of 10 student/i)).toBeInTheDocument();
  });

  it("renders a progressbar with aria label per issue", () => {
    const issues: CommonIssue[] = [
      { skill_dimension: "evidence", avg_score: 0.45, affected_student_count: 6 },
    ];
    render(<CommonIssuesPanel issues={issues} totalStudentCount={10} />, {
      wrapper,
    });
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    expect(bar).toHaveAttribute(
      "aria-label",
      expect.stringContaining("evidence"),
    );
  });

  it("shows class average percentage", () => {
    const issues: CommonIssue[] = [
      { skill_dimension: "thesis", avg_score: 0.53, affected_student_count: 4 },
    ];
    render(<CommonIssuesPanel issues={issues} totalStudentCount={8} />, {
      wrapper,
    });
    expect(screen.getByText(/class average: 53%/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// ScoreDistributionPanel
// ---------------------------------------------------------------------------

describe("ScoreDistributionPanel", () => {
  it("shows empty state when distributions is empty", () => {
    render(
      <ScoreDistributionPanel distributions={{}} totalStudentCount={10} />,
      { wrapper },
    );
    expect(
      screen.getByText(/no distribution data available/i),
    ).toBeInTheDocument();
  });

  it("renders one histogram per skill dimension", () => {
    const distributions: Record<string, ScoreBucket[]> = {
      evidence: [
        { label: "0-20%", count: 1 },
        { label: "20-40%", count: 3 },
        { label: "40-60%", count: 4 },
        { label: "60-80%", count: 2 },
        { label: "80-100%", count: 0 },
      ],
      thesis: [
        { label: "0-20%", count: 0 },
        { label: "20-40%", count: 2 },
        { label: "40-60%", count: 3 },
        { label: "60-80%", count: 4 },
        { label: "80-100%", count: 1 },
      ],
    };
    render(
      <ScoreDistributionPanel
        distributions={distributions}
        totalStudentCount={10}
      />,
      { wrapper },
    );
    // Each histogram renders a heading with the skill name
    expect(screen.getByText(/evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/thesis/i)).toBeInTheDocument();
  });

  it("renders a histogram figure with aria-label for each skill", () => {
    const distributions: Record<string, ScoreBucket[]> = {
      evidence: [
        { label: "0-20%", count: 2 },
        { label: "20-40%", count: 3 },
        { label: "40-60%", count: 3 },
        { label: "60-80%", count: 2 },
        { label: "80-100%", count: 0 },
      ],
    };
    render(
      <ScoreDistributionPanel
        distributions={distributions}
        totalStudentCount={10}
      />,
      { wrapper },
    );
    const histogram = screen.getByRole("img", {
      name: /score distribution histogram for evidence/i,
    });
    expect(histogram).toBeInTheDocument();
  });

  it("applies amber ring to outlier bucket 0-20% when non-empty", () => {
    const distributions: Record<string, ScoreBucket[]> = {
      evidence: [
        { label: "0-20%", count: 2 },
        { label: "20-40%", count: 3 },
        { label: "40-60%", count: 3 },
        { label: "60-80%", count: 2 },
        { label: "80-100%", count: 0 },
      ],
    };
    render(
      <ScoreDistributionPanel
        distributions={distributions}
        totalStudentCount={10}
      />,
      { wrapper },
    );
    // The bar for the 0–20% bucket should have ring-amber-500
    const outlierBar = screen
      .getByLabelText(/0-20%: 2 students/i);
    expect(outlierBar.className).toContain("ring-amber-500");
  });

  it("does not apply amber ring to mid-range non-outlier buckets", () => {
    const distributions: Record<string, ScoreBucket[]> = {
      evidence: [
        { label: "0-20%", count: 0 },
        { label: "20-40%", count: 2 },
        { label: "40-60%", count: 5 },
        { label: "60-80%", count: 3 },
        { label: "80-100%", count: 0 },
      ],
    };
    render(
      <ScoreDistributionPanel
        distributions={distributions}
        totalStudentCount={10}
      />,
      { wrapper },
    );
    // 40-60% bucket: 5 students — should NOT have the amber ring
    const midBar = screen.getByLabelText(/40-60%: 5 students/i);
    expect(midBar.className).not.toContain("ring-amber-500");
  });
});

// ---------------------------------------------------------------------------
// TrendChart
// ---------------------------------------------------------------------------

describe("TrendChart", () => {
  it("shows placeholder when fewer than 2 completed assignments", () => {
    const assignments = [makeAssignment("a-001", "Assignment 1", "complete")];
    render(<TrendChart assignments={assignments} />, { wrapper });
    expect(
      screen.getByText(/at least 2 assignments/i),
    ).toBeInTheDocument();
  });

  it("shows placeholder when no completed assignments", () => {
    render(<TrendChart assignments={[]} />, { wrapper });
    expect(
      screen.getByText(/at least 2 assignments/i),
    ).toBeInTheDocument();
  });

  it("shows placeholder for non-completed assignments only", () => {
    const assignments = [
      makeAssignment("a-001", "Assignment 1", "open"),
      makeAssignment("a-002", "Assignment 2", "grading"),
    ];
    render(<TrendChart assignments={assignments} />, { wrapper });
    expect(
      screen.getByText(/at least 2 assignments/i),
    ).toBeInTheDocument();
  });

  it("shows loading skeleton while analytics queries are pending", () => {
    mockGetAssignmentAnalytics.mockReturnValue(new Promise(() => {}));
    const assignments = [
      makeAssignment("a-001", "Assignment 1"),
      makeAssignment("a-002", "Assignment 2"),
    ];
    render(<TrendChart assignments={assignments} />, { wrapper });
    const skeleton = document.querySelector('[aria-busy="true"]');
    expect(skeleton).toBeTruthy();
  });

  it("renders SVG trend chart when 2+ completed assignments have score data", async () => {
    mockGetAssignmentAnalytics
      .mockResolvedValueOnce(makeAnalytics("a-001", 0.65))
      .mockResolvedValueOnce(makeAnalytics("a-002", 0.78));

    const assignments = [
      makeAssignment("a-001", "Assignment 1"),
      makeAssignment("a-002", "Assignment 2"),
    ];
    render(<TrendChart assignments={assignments} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("img", {
          name: /cross-assignment class performance trend chart/i,
        }),
      ).toBeInTheDocument();
    });
  });

  it("shows error alert when analytics queries fail", async () => {
    mockGetAssignmentAnalytics.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server error" }),
    );
    const assignments = [
      makeAssignment("a-001", "Assignment 1"),
      makeAssignment("a-002", "Assignment 2"),
    ];
    render(<TrendChart assignments={assignments} />, { wrapper });
    await waitFor(() => {
      expect(
        screen.getByText(/failed to load assignment analytics/i),
      ).toBeInTheDocument();
    });
  });

  it("renders accessible data table alongside the SVG chart", async () => {
    mockGetAssignmentAnalytics
      .mockResolvedValueOnce(makeAnalytics("a-001", 0.65))
      .mockResolvedValueOnce(makeAnalytics("a-002", 0.78));

    const assignments = [
      makeAssignment("a-001", "Assignment One"),
      makeAssignment("a-002", "Assignment Two"),
    ];
    render(<TrendChart assignments={assignments} />, { wrapper });

    await waitFor(() => {
      const table = screen.getByRole("table", {
        name: /cross-assignment trend data/i,
      });
      expect(table).toBeInTheDocument();
      expect(table.textContent).toContain("Assignment One");
      expect(table.textContent).toContain("Assignment Two");
    });
  });

  it("shows placeholder when all assignment scores are null", async () => {
    mockGetAssignmentAnalytics
      .mockResolvedValueOnce(makeAnalytics("a-001", null))
      .mockResolvedValueOnce(makeAnalytics("a-002", null));

    const assignments = [
      makeAssignment("a-001", "Assignment 1"),
      makeAssignment("a-002", "Assignment 2"),
    ];
    render(<TrendChart assignments={assignments} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/not enough graded data/i),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// ClassInsightsPanel
// ---------------------------------------------------------------------------

describe("ClassInsightsPanel", () => {
  it("shows loading skeleton while insights are loading", () => {
    mockGetClassInsights.mockReturnValue(new Promise(() => {}));
    render(<ClassInsightsPanel classId={CLASS_ID} assignments={[]} />, {
      wrapper,
    });
    const skeleton = document.querySelector('[aria-busy="true"]');
    expect(skeleton).toBeTruthy();
  });

  it("shows error alert when insights fetch fails", async () => {
    mockGetClassInsights.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server error" }),
    );
    render(<ClassInsightsPanel classId={CLASS_ID} assignments={[]} />, {
      wrapper,
    });
    await waitFor(() => {
      expect(
        screen.getByText(/failed to load class insights/i),
      ).toBeInTheDocument();
    });
  });

  it("shows empty state when graded_essay_count is 0", async () => {
    mockGetClassInsights.mockResolvedValue(
      makeInsights({ graded_essay_count: 0 }),
    );
    render(<ClassInsightsPanel classId={CLASS_ID} assignments={[]} />, {
      wrapper,
    });
    await waitFor(() => {
      expect(screen.getByText(/no insight data yet/i)).toBeInTheDocument();
    });
  });

  it("renders Common Issues section heading", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    render(<ClassInsightsPanel classId={CLASS_ID} assignments={[]} />, {
      wrapper,
    });
    await waitFor(() => {
      expect(screen.getByText(/common issues/i)).toBeInTheDocument();
    });
  });

  it("renders Score Distributions section heading", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    render(<ClassInsightsPanel classId={CLASS_ID} assignments={[]} />, {
      wrapper,
    });
    await waitFor(() => {
      expect(screen.getByText(/score distributions/i)).toBeInTheDocument();
    });
  });

  it("renders Cross-Assignment Trend section heading", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    render(<ClassInsightsPanel classId={CLASS_ID} assignments={[]} />, {
      wrapper,
    });
    await waitFor(() => {
      const headings = screen.getAllByRole("heading");
      const trendHeading = headings.find((h) =>
        /cross-assignment trend/i.test(h.textContent ?? ""),
      );
      expect(trendHeading).toBeInTheDocument();
    });
  });

  it("renders common issue skill dimensions from insights data", async () => {
    mockGetClassInsights.mockResolvedValue(
      makeInsights({
        common_issues: [
          {
            skill_dimension: "evidence",
            avg_score: 0.45,
            affected_student_count: 6,
          },
        ],
        score_distributions: {},
      }),
    );
    render(<ClassInsightsPanel classId={CLASS_ID} assignments={[]} />, {
      wrapper,
    });
    await waitFor(() => {
      // The common issues panel renders a list; find the item with the skill name
      const list = screen.getByRole("list", { name: /common class issues/i });
      expect(list).toBeInTheDocument();
      expect(list.textContent).toMatch(/evidence/i);
    });
  });

  it("renders score distribution histograms for each skill", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    render(<ClassInsightsPanel classId={CLASS_ID} assignments={[]} />, {
      wrapper,
    });
    await waitFor(() => {
      // Evidence and thesis histograms should both appear
      const histograms = screen.getAllByRole("img", {
        name: /score distribution histogram for/i,
      });
      expect(histograms.length).toBeGreaterThanOrEqual(2);
    });
  });
});
