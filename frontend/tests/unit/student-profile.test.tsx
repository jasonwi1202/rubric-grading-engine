/**
 * Tests for the Student Profile page (M5.5 — Student profile UI).
 *
 * Covers:
 * - StudentProfilePage: shows loading skeleton while fetching
 * - StudentProfilePage: shows error alert on student fetch failure
 * - StudentProfilePage: shows "no skill data" empty state when skill_profile is null
 * - StudentProfilePage: renders skill bar chart from skill_profile data
 * - StudentProfilePage: shows strengths section for skills with avg_score >= 0.7
 * - StudentProfilePage: shows gaps (Needs Support) section for skills with avg_score < 0.5
 * - StudentProfilePage: hides strengths/gaps when no qualifying skills
 * - StudentProfilePage: shows "no history" empty state when history is empty
 * - StudentProfilePage: renders assignment history rows with links and scores
 * - StudentProfilePage: shows history error alert on history fetch failure
 * - StudentProfilePage: renders teacher notes textarea pre-filled from server
 * - StudentProfilePage: saves notes when Save button is clicked
 * - StudentProfilePage: shows "Notes saved" confirmation after successful save
 * - StudentProfilePage: shows save error on mutation failure
 * - StudentProfilePage: Save button disabled while mutation is pending
 * - SkillBar (via page): progressbar aria attributes set correctly
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and placeholder names only.
 * - No credential-format strings in test data.
 * - No student data logged; error assertions use static UI strings only.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — must come before component imports
// ---------------------------------------------------------------------------

const mockGetStudentWithProfile = vi.fn();
const mockGetStudentHistory = vi.fn();
const mockPatchStudent = vi.fn();

vi.mock("@/lib/api/students", () => ({
  getStudentWithProfile: (...args: unknown[]) =>
    mockGetStudentWithProfile(...args),
  getStudentHistory: (...args: unknown[]) => mockGetStudentHistory(...args),
  patchStudent: (...args: unknown[]) => mockPatchStudent(...args),
}));

// Mock useParams so the page can read studentId without a real router
vi.mock("next/navigation", () => ({
  useParams: () => ({ studentId: "stu-001" }),
}));

// ---------------------------------------------------------------------------
// Component under test
// ---------------------------------------------------------------------------

import StudentProfilePage from "@/app/(dashboard)/dashboard/students/[studentId]/page";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Factory — no real student names (FERPA). */
function makeStudent(overrides: Record<string, unknown> = {}) {
  return {
    id: "stu-001",
    teacher_id: "tch-001",
    full_name: "Test Student A",
    external_id: null,
    teacher_notes: null,
    created_at: "2026-01-01T00:00:00Z",
    skill_profile: null,
    ...overrides,
  };
}

function makeSkillProfile(
  skills: Record<
    string,
    { avg_score: number; trend: "improving" | "stable" | "declining"; data_points: number }
  > = {},
) {
  const skill_scores: Record<string, object> = {};
  for (const [name, s] of Object.entries(skills)) {
    skill_scores[name] = {
      avg_score: s.avg_score,
      trend: s.trend,
      data_points: s.data_points,
      last_updated: "2026-03-01T00:00:00Z",
    };
  }
  return {
    skill_scores,
    assignment_count: Object.values(skills).reduce(
      (sum, s) => Math.max(sum, s.data_points),
      0,
    ),
    last_updated_at: "2026-03-01T00:00:00Z",
  };
}

function makeHistoryItem(overrides: Record<string, unknown> = {}) {
  return {
    assignment_id: "asgn-001",
    assignment_title: "Essay Assignment One",
    class_id: "cls-001",
    grade_id: "grd-001",
    essay_id: "ess-001",
    total_score: 80,
    max_possible_score: 100,
    locked_at: "2026-02-15T10:00:00Z",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

describe("StudentProfilePage — loading and error states", () => {
  it("shows loading skeleton while student data is fetching", () => {
    // Never resolves
    mockGetStudentWithProfile.mockReturnValue(new Promise(() => {}));
    mockGetStudentHistory.mockReturnValue(new Promise(() => {}));

    render(<StudentProfilePage />, { wrapper });

    // Skill Profile heading should be present (section is always rendered)
    // and the loading skeleton for that section should be aria-busy
    const busyElements = document.querySelectorAll('[aria-busy="true"]');
    expect(busyElements.length).toBeGreaterThan(0);
  });

  it("shows error alert when student fetch fails", async () => {
    mockGetStudentWithProfile.mockRejectedValue(
      new ApiError(403, { code: "FORBIDDEN", message: "Forbidden" }),
    );
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to load student profile/i),
      ).toBeInTheDocument();
    });
  });

  it("shows error alert when history fetch fails", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Error" }),
    );

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to load assignment history/i),
      ).toBeInTheDocument();
    });
  });
});

describe("StudentProfilePage — empty states", () => {
  it("shows 'no skill data' empty state when skill_profile is null", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/No skill data yet/i),
      ).toBeInTheDocument();
    });
  });

  it("shows 'no graded assignments' empty state when history is empty", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/No graded assignments yet/i),
      ).toBeInTheDocument();
    });
  });
});

describe("StudentProfilePage — skill visualization", () => {
  it("renders skill bars from skill_profile data", async () => {
    const student = makeStudent({
      skill_profile: makeSkillProfile({
        thesis: { avg_score: 0.8, trend: "improving", data_points: 3 },
        evidence: { avg_score: 0.6, trend: "stable", data_points: 3 },
        organization: { avg_score: 0.4, trend: "declining", data_points: 3 },
      }),
    });
    mockGetStudentWithProfile.mockResolvedValue(student);
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      // All three skill names should appear (may appear more than once due to strengths/gaps sections)
      expect(screen.getAllByText(/thesis/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/evidence/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/organization/i).length).toBeGreaterThan(0);
    });
  });

  it("sets correct aria attributes on skill progressbars", async () => {
    const student = makeStudent({
      skill_profile: makeSkillProfile({
        thesis: { avg_score: 0.75, trend: "stable", data_points: 2 },
      }),
    });
    mockGetStudentWithProfile.mockResolvedValue(student);
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      const bars = screen.getAllByRole("progressbar");
      expect(bars.length).toBeGreaterThan(0);
      // thesis bar at 75%
      const thesisBar = bars.find(
        (b) => b.getAttribute("aria-valuenow") === "75",
      );
      expect(thesisBar).toBeDefined();
    });
  });

  it("shows trend badges for each skill", async () => {
    const student = makeStudent({
      skill_profile: makeSkillProfile({
        thesis: { avg_score: 0.8, trend: "improving", data_points: 3 },
        evidence: { avg_score: 0.5, trend: "stable", data_points: 3 },
        organization: { avg_score: 0.3, trend: "declining", data_points: 3 },
      }),
    });
    mockGetStudentWithProfile.mockResolvedValue(student);
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/Improving/i)).toBeInTheDocument();
      expect(screen.getByText(/Stable/i)).toBeInTheDocument();
      expect(screen.getByText(/Declining/i)).toBeInTheDocument();
    });
  });
});

describe("StudentProfilePage — strengths and gaps", () => {
  it("shows Strengths section for high-scoring skills", async () => {
    const student = makeStudent({
      skill_profile: makeSkillProfile({
        thesis: { avg_score: 0.85, trend: "improving", data_points: 3 },
      }),
    });
    mockGetStudentWithProfile.mockResolvedValue(student);
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Strengths")).toBeInTheDocument();
    });
  });

  it("shows Needs Support section for low-scoring skills", async () => {
    const student = makeStudent({
      skill_profile: makeSkillProfile({
        evidence: { avg_score: 0.35, trend: "declining", data_points: 3 },
      }),
    });
    mockGetStudentWithProfile.mockResolvedValue(student);
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Needs Support")).toBeInTheDocument();
    });
  });

  it("hides strengths/gaps sections when no qualifying skills", async () => {
    const student = makeStudent({
      skill_profile: makeSkillProfile({
        // One data_point is insufficient (< 2) for strengths/gaps callouts
        thesis: { avg_score: 0.9, trend: "improving", data_points: 1 },
        evidence: { avg_score: 0.2, trend: "declining", data_points: 1 },
      }),
    });
    mockGetStudentWithProfile.mockResolvedValue(student);
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      // Bars still visible
      expect(screen.getByText(/thesis/i)).toBeInTheDocument();
      // But no Strengths/Needs Support callouts
      expect(screen.queryByText("Strengths")).not.toBeInTheDocument();
      expect(screen.queryByText("Needs Support")).not.toBeInTheDocument();
    });
  });
});

describe("StudentProfilePage — assignment history", () => {
  it("renders history rows with assignment titles and scores", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockResolvedValue([
      makeHistoryItem({
        assignment_title: "Essay Assignment One",
        total_score: 80,
        max_possible_score: 100,
      }),
      makeHistoryItem({
        grade_id: "grd-002",
        assignment_id: "asgn-002",
        assignment_title: "Essay Assignment Two",
        total_score: 45,
        max_possible_score: 60,
      }),
    ]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Essay Assignment One")).toBeInTheDocument();
      expect(screen.getByText("Essay Assignment Two")).toBeInTheDocument();
      expect(screen.getByText("80 / 100")).toBeInTheDocument();
      expect(screen.getByText("45 / 60")).toBeInTheDocument();
    });
  });

  it("renders assignment links using assignment_id (UUID, not student name)", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockResolvedValue([
      makeHistoryItem({ assignment_id: "asgn-uuid-1234" }),
    ]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      const links = screen.getAllByRole("link");
      const historyLink = links.find(
        (l) =>
          l.getAttribute("href")?.includes("asgn-uuid-1234"),
      );
      expect(historyLink).toBeDefined();
    });
  });
});

describe("StudentProfilePage — teacher notes", () => {
  it("pre-fills notes textarea from server data", async () => {
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudent({ teacher_notes: "Watch evidence integration." }),
    );
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      const textarea = screen.getByRole("textbox", {
        name: /private teacher notes/i,
      }) as HTMLTextAreaElement;
      expect(textarea.value).toBe("Watch evidence integration.");
    });
  });

  it("pre-fills empty string when teacher_notes is null", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent({ teacher_notes: null }));
    mockGetStudentHistory.mockResolvedValue([]);

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      const textarea = screen.getByRole("textbox", {
        name: /private teacher notes/i,
      }) as HTMLTextAreaElement;
      expect(textarea.value).toBe("");
    });
  });

  it("calls patchStudent with updated notes when Save is clicked", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockResolvedValue([]);
    mockPatchStudent.mockResolvedValue(
      makeStudent({ teacher_notes: "New note text." }),
    );

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() =>
      screen.getByRole("textbox", { name: /private teacher notes/i }),
    );

    const textarea = screen.getByRole("textbox", {
      name: /private teacher notes/i,
    });
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "New note text.");

    const saveBtn = screen.getByRole("button", { name: /save notes/i });
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockPatchStudent).toHaveBeenCalledWith("stu-001", {
        teacher_notes: "New note text.",
      });
    });
  });

  it("shows 'Notes saved.' confirmation after successful save", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockResolvedValue([]);
    mockPatchStudent.mockResolvedValue(
      makeStudent({ teacher_notes: "Saved content." }),
    );

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() =>
      screen.getByRole("textbox", { name: /private teacher notes/i }),
    );

    // Type something to make the form dirty and enable the Save button
    const textarea = screen.getByRole("textbox", {
      name: /private teacher notes/i,
    });
    await userEvent.type(textarea, "Saved content.");

    const saveBtn = screen.getByRole("button", { name: /save notes/i });
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(screen.getByText(/Notes saved\./i)).toBeInTheDocument();
    });
  });

  it("shows save error message on mutation failure", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockResolvedValue([]);
    mockPatchStudent.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server error" }),
    );

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() =>
      screen.getByRole("textbox", { name: /private teacher notes/i }),
    );

    // Type something to make the form dirty and enable the Save button
    const textarea = screen.getByRole("textbox", {
      name: /private teacher notes/i,
    });
    await userEvent.type(textarea, "Some note text.");

    const saveBtn = screen.getByRole("button", { name: /save notes/i });
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to save notes/i),
      ).toBeInTheDocument();
    });
  });

  it("disables Save button while mutation is pending", async () => {
    mockGetStudentWithProfile.mockResolvedValue(makeStudent());
    mockGetStudentHistory.mockResolvedValue([]);
    // Never resolves — keeps the mutation pending
    mockPatchStudent.mockReturnValue(new Promise(() => {}));

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() =>
      screen.getByRole("textbox", { name: /private teacher notes/i }),
    );

    // Type something to enable the Save button first
    const textarea = screen.getByRole("textbox", {
      name: /private teacher notes/i,
    });
    await userEvent.type(textarea, "Some note.");

    const saveBtn = screen.getByRole("button", { name: /save notes/i });
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /saving/i }),
      ).toBeDisabled();
    });
  });

  it("sends null to backend when clearing all notes text", async () => {
    mockGetStudentWithProfile.mockResolvedValue(
      makeStudent({ teacher_notes: "Existing notes." }),
    );
    mockGetStudentHistory.mockResolvedValue([]);
    mockPatchStudent.mockResolvedValue(makeStudent({ teacher_notes: null }));

    render(<StudentProfilePage />, { wrapper });

    await waitFor(() => {
      const textarea = screen.getByRole("textbox", {
        name: /private teacher notes/i,
      }) as HTMLTextAreaElement;
      expect(textarea.value).toBe("Existing notes.");
    });

    // Clear the textarea — should send null to clear the field
    const textarea = screen.getByRole("textbox", {
      name: /private teacher notes/i,
    });
    await userEvent.clear(textarea);

    const saveBtn = screen.getByRole("button", { name: /save notes/i });
    await userEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockPatchStudent).toHaveBeenCalledWith("stu-001", {
        teacher_notes: null,
      });
    });
  });
});
