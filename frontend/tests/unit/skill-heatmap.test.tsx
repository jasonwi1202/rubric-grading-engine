/**
 * Tests for the SkillHeatmap component (M5.7 — Skill heatmap UI).
 *
 * Covers:
 * - SkillHeatmap: shows loading skeleton while insights/students are fetching
 * - SkillHeatmap: shows error alert when insights fetch fails
 * - SkillHeatmap: shows error alert when students fetch fails
 * - SkillHeatmap: shows "no skill data" empty state when graded_essay_count is 0
 * - SkillHeatmap: shows "no skill dimensions" empty state when skill_averages is empty
 * - SkillHeatmap: renders skill columns from insights.skill_averages keys
 * - SkillHeatmap: renders student rows with student names
 * - SkillHeatmap: student names are links to /dashboard/students/{id}
 * - SkillHeatmap: cells display formatted percentage for students with skill data
 * - SkillHeatmap: cells display "—" for students with no data for a skill
 * - SkillHeatmap: renders accessible legend
 * - SkillHeatmap: default sort is by student name ascending
 * - SkillHeatmap: clicking a skill column header sorts rows by that skill
 * - SkillHeatmap: clicking the same column header twice reverses sort direction
 * - SkillHeatmap: clicking Student header sorts by student name
 * - SkillHeatmap: sort indicators (↑/↓/↕) update on column click
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and placeholder names only.
 * - No credential-format strings in test data.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — must be declared before component imports
// ---------------------------------------------------------------------------

const mockGetClassInsights = vi.fn();
const mockListStudents = vi.fn();
const mockGetStudentWithProfile = vi.fn();

vi.mock("@/lib/api/classes", () => ({
  getClassInsights: (...args: unknown[]) => mockGetClassInsights(...args),
  listStudents: (...args: unknown[]) => mockListStudents(...args),
}));

vi.mock("@/lib/api/students", () => ({
  getStudentWithProfile: (...args: unknown[]) =>
    mockGetStudentWithProfile(...args),
}));

// Mock Link so href is rendered as an <a> element in jsdom
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

// ---------------------------------------------------------------------------
// Component under test
// ---------------------------------------------------------------------------

import { SkillHeatmap } from "@/components/classes/SkillHeatmap";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const CLASS_ID = "cls-001";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/**
 * Factory — class insights response. No real class names.
 */
function makeInsights(
  overrides: Partial<{
    graded_essay_count: number;
    skill_averages: Record<
      string,
      { avg_score: number; student_count: number; data_points: number }
    >;
  }> = {},
) {
  return {
    class_id: CLASS_ID,
    assignment_count: 2,
    student_count: 2,
    graded_essay_count: 2,
    skill_averages: {
      evidence: { avg_score: 0.65, student_count: 2, data_points: 4 },
      thesis: { avg_score: 0.8, student_count: 2, data_points: 4 },
    },
    score_distributions: {},
    common_issues: [],
    ...overrides,
  };
}

/**
 * Factory — enrolled student response. Uses synthetic names only (FERPA).
 */
function makeEnrolledStudent(id: string, name: string) {
  return {
    enrollment_id: `enr-${id}`,
    enrolled_at: "2026-01-01T00:00:00Z",
    student: {
      id,
      teacher_id: "tch-001",
      full_name: name,
      external_id: null,
      created_at: "2026-01-01T00:00:00Z",
    },
  };
}

/**
 * Factory — student with profile. Skill scores use avg_score in [0,1].
 */
function makeStudentWithProfile(
  id: string,
  name: string,
  skills: Record<string, number> | null = null,
) {
  const skill_scores: Record<string, object> = {};
  if (skills) {
    for (const [k, v] of Object.entries(skills)) {
      skill_scores[k] = {
        avg_score: v,
        trend: "stable" as const,
        data_points: 2,
        last_updated: "2026-03-01T00:00:00Z",
      };
    }
  }
  return {
    id,
    teacher_id: "tch-001",
    full_name: name,
    external_id: null,
    teacher_notes: null,
    created_at: "2026-01-01T00:00:00Z",
    skill_profile: skills
      ? {
          skill_scores,
          assignment_count: 2,
          last_updated_at: "2026-03-01T00:00:00Z",
        }
      : null,
  };
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

describe("SkillHeatmap — loading state", () => {
  it("shows loading skeleton while data is fetching", () => {
    mockGetClassInsights.mockReturnValue(new Promise(() => {}));
    mockListStudents.mockReturnValue(new Promise(() => {}));

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    const skeleton = document.querySelector('[aria-busy="true"]');
    expect(skeleton).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

describe("SkillHeatmap — error states", () => {
  it("shows error alert when insights fetch fails", async () => {
    mockGetClassInsights.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server error" }),
    );
    mockListStudents.mockResolvedValue([]);

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to load skill heatmap/i),
      ).toBeInTheDocument();
    });
  });

  it("shows error alert when students fetch fails", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server error" }),
    );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to load skill heatmap/i),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Empty states
// ---------------------------------------------------------------------------

describe("SkillHeatmap — empty states", () => {
  it("shows 'no skill data' empty state when graded_essay_count is 0", async () => {
    mockGetClassInsights.mockResolvedValue(
      makeInsights({ graded_essay_count: 0, skill_averages: {} }),
    );
    mockListStudents.mockResolvedValue([]);

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/No skill data yet/i)).toBeInTheDocument();
    });
  });

  it("shows 'no skill dimensions' empty state when skill_averages is empty but essays exist", async () => {
    mockGetClassInsights.mockResolvedValue(
      makeInsights({ graded_essay_count: 2, skill_averages: {} }),
    );
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-001", "Student A"),
    ]);
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudentWithProfile("stu-001", "Student A", null),
    );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/No skill dimensions found/i),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe("SkillHeatmap — rendering", () => {
  it("renders skill columns from insights.skill_averages", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-001", "Student A"),
    ]);
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudentWithProfile("stu-001", "Student A", {
        thesis: 0.8,
        evidence: 0.6,
      }),
    );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      // Column headers for skills
      expect(screen.getByText(/thesis/i)).toBeInTheDocument();
      expect(screen.getByText(/evidence/i)).toBeInTheDocument();
    });
  });

  it("renders student rows with student names", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-001", "Student Alpha"),
      makeEnrolledStudent("stu-002", "Student Beta"),
    ]);
    mockGetStudentWithProfile
      .mockResolvedValueOnce(
        makeStudentWithProfile("stu-001", "Student Alpha", {
          thesis: 0.8,
          evidence: 0.6,
        }),
      )
      .mockResolvedValueOnce(
        makeStudentWithProfile("stu-002", "Student Beta", {
          thesis: 0.5,
          evidence: 0.35,
        }),
      );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Student Alpha")).toBeInTheDocument();
      expect(screen.getByText("Student Beta")).toBeInTheDocument();
    });
  });

  it("renders student names as links to /dashboard/students/{id}", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-uuid-1234", "Student Alpha"),
    ]);
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudentWithProfile("stu-uuid-1234", "Student Alpha", {
        thesis: 0.8,
      }),
    );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      const link = screen.getByRole("link", { name: "Student Alpha" });
      expect(link).toHaveAttribute(
        "href",
        "/dashboard/students/stu-uuid-1234",
      );
    });
  });

  it("displays formatted percentage in cells for students with skill data", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-001", "Student Alpha"),
    ]);
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudentWithProfile("stu-001", "Student Alpha", {
        thesis: 0.75,
        evidence: 0.4,
      }),
    );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      // thesis at 75%
      expect(screen.getByText("75%")).toBeInTheDocument();
      // evidence at 40%
      expect(screen.getByText("40%")).toBeInTheDocument();
    });
  });

  it("displays '—' in cells for skills a student has no data for", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-001", "Student Alpha"),
    ]);
    // Student has thesis but not evidence
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudentWithProfile("stu-001", "Student Alpha", { thesis: 0.8 }),
    );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      // thesis should render
      expect(screen.getByText("80%")).toBeInTheDocument();
      // evidence missing → em-dash placeholder
      expect(screen.getByText("—")).toBeInTheDocument();
    });
  });

  it("renders the accessible colour legend", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-001", "Student A"),
    ]);
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudentWithProfile("stu-001", "Student A", { thesis: 0.8 }),
    );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByLabelText(/heatmap colour legend/i),
      ).toBeInTheDocument();
      expect(screen.getByText(/≥70%/i)).toBeInTheDocument();
      expect(screen.getByText(/40–69%/i)).toBeInTheDocument();
      expect(screen.getByText(/needs support/i)).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------

describe("SkillHeatmap — sorting", () => {
  async function renderWithTwoStudents() {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-001", "Zebra Student"),
      makeEnrolledStudent("stu-002", "Alpha Student"),
    ]);
    mockGetStudentWithProfile
      .mockImplementation((id: string) => {
        if (id === "stu-001") {
          return Promise.resolve(
            makeStudentWithProfile("stu-001", "Zebra Student", {
              thesis: 0.9,
              evidence: 0.3,
            }),
          );
        }
        return Promise.resolve(
          makeStudentWithProfile("stu-002", "Alpha Student", {
            thesis: 0.4,
            evidence: 0.8,
          }),
        );
      });

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    // Wait for the table to render
    await waitFor(() => {
      expect(screen.getByRole("grid")).toBeInTheDocument();
    });
    // Wait for student names to appear
    await waitFor(() => {
      expect(screen.getByText("Alpha Student")).toBeInTheDocument();
      expect(screen.getByText("Zebra Student")).toBeInTheDocument();
    });
  }

  it("default sort is student name ascending (Alpha before Zebra)", async () => {
    await renderWithTwoStudents();

    const rows = screen.getAllByRole("row");
    // rows[0] is the header; rows[1] is first data row
    expect(within(rows[1]).getByText("Alpha Student")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Zebra Student")).toBeInTheDocument();
  });

  it("clicking Student header toggles to descending (Zebra before Alpha)", async () => {
    const user = userEvent.setup();
    await renderWithTwoStudents();

    // Click Student header to toggle to descending (already ascending)
    await user.click(screen.getByRole("button", { name: /sort by student name/i }));

    await waitFor(() => {
      const rows = screen.getAllByRole("row");
      expect(within(rows[1]).getByText("Zebra Student")).toBeInTheDocument();
      expect(within(rows[2]).getByText("Alpha Student")).toBeInTheDocument();
    });
  });

  it("clicking a skill column header sorts by that skill ascending", async () => {
    const user = userEvent.setup();
    await renderWithTwoStudents();

    // thesis: Zebra=0.9, Alpha=0.4 → ascending → Alpha first
    await user.click(screen.getByRole("button", { name: /sort by thesis score/i }));

    await waitFor(() => {
      const rows = screen.getAllByRole("row");
      expect(within(rows[1]).getByText("Alpha Student")).toBeInTheDocument();
      expect(within(rows[2]).getByText("Zebra Student")).toBeInTheDocument();
    });
  });

  it("clicking the same skill column header again reverses to descending", async () => {
    const user = userEvent.setup();
    await renderWithTwoStudents();

    // First click: sort thesis ascending (Alpha first)
    await user.click(screen.getByRole("button", { name: /sort by thesis score/i }));
    // Second click: descending (Zebra first)
    await user.click(screen.getByRole("button", { name: /sort by thesis score/i }));

    await waitFor(() => {
      const rows = screen.getAllByRole("row");
      expect(within(rows[1]).getByText("Zebra Student")).toBeInTheDocument();
      expect(within(rows[2]).getByText("Alpha Student")).toBeInTheDocument();
    });
  });

  it("sort indicator shows ↑ when column is sorted ascending", async () => {
    const user = userEvent.setup();
    await renderWithTwoStudents();

    // Click thesis to sort ascending
    await user.click(screen.getByRole("button", { name: /sort by thesis score/i }));

    // The sort indicator ↑ should be visible (aria-hidden but in DOM)
    await waitFor(() => {
      // Find the thesis sort button and check it contains ↑
      const thesisBtn = screen.getByRole("button", { name: /sort by thesis score/i });
      expect(thesisBtn.textContent).toContain("↑");
    });
  });

  it("sort indicator shows ↕ for unsorted columns", async () => {
    await renderWithTwoStudents();

    // evidence column is unsorted by default (student sort is active)
    await waitFor(() => {
      const evidenceBtn = screen.getByRole("button", { name: /sort by evidence score/i });
      expect(evidenceBtn.textContent).toContain("↕");
    });
  });
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

describe("SkillHeatmap — navigation", () => {
  it("student name links use entity ID in href, not student name", async () => {
    mockGetClassInsights.mockResolvedValue(makeInsights());
    mockListStudents.mockResolvedValue([
      makeEnrolledStudent("stu-uuid-9999", "Student A"),
    ]);
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudentWithProfile("stu-uuid-9999", "Student A", { thesis: 0.7 }),
    );

    render(<SkillHeatmap classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      const link = screen.getByRole("link", { name: "Student A" });
      // href uses UUID, not student name
      expect(link.getAttribute("href")).toBe(
        "/dashboard/students/stu-uuid-9999",
      );
      expect(link.getAttribute("href")).not.toContain("Student A");
    });
  });
});
