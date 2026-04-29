/**
 * Tests for SkillGroupsPanel — M6.3 Auto-Grouping UI.
 *
 * Covers:
 * - SkillGroupsPanel: shows loading skeleton while groups are fetching
 * - SkillGroupsPanel: shows error alert when fetch fails
 * - SkillGroupsPanel: shows empty state when no groups have been computed
 * - SkillGroupsPanel: renders group list with name, skill key, and student count
 * - SkillGroupsPanel: renders stability badges (New / Persistent / Resolved)
 * - SkillGroupsPanel: expand toggle reveals student members
 * - SkillGroupsPanel: collapsed by default (members not visible)
 * - SkillGroupsPanel: expand toggle shows "Add a student" selector when enrolled students exist
 * - SkillGroupsPanel: "Remove" button calls updateGroupMembers and invalidates cache
 * - SkillGroupsPanel: "Add a student" selector calls updateGroupMembers with new list
 * - SkillGroupsPanel: exited groups do not show remove buttons or add selector
 * - SkillGroupsPanel: heatmap link calls onNavigateToHeatmap callback
 * - SkillGroupsPanel: "Resolved" groups listed in separate section
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
// Mocks — declared before component imports per Vitest hoisting rules
// ---------------------------------------------------------------------------

const mockGetClassGroups = vi.fn();
const mockListStudents = vi.fn();
const mockUpdateGroupMembers = vi.fn();

vi.mock("@/lib/api/classes", () => ({
  getClassGroups: (...args: unknown[]) => mockGetClassGroups(...args),
  listStudents: (...args: unknown[]) => mockListStudents(...args),
  updateGroupMembers: (...args: unknown[]) => mockUpdateGroupMembers(...args),
}));

// ---------------------------------------------------------------------------
// Component imports (after mock declarations)
// ---------------------------------------------------------------------------

import { SkillGroupsPanel } from "@/components/classes/SkillGroupsPanel";
import { ApiError } from "@/lib/api/errors";
import type {
  ClassGroupsResponse,
  StudentGroupResponse,
  EnrolledStudentResponse,
} from "@/lib/api/classes";

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

function makeStudent(
  id: string,
  full_name: string,
  external_id: string | null = null,
) {
  return { id, full_name, external_id };
}

function makeGroup(overrides: Partial<StudentGroupResponse> = {}): StudentGroupResponse {
  return {
    id: "grp-001",
    skill_key: "evidence",
    label: "Evidence",
    student_count: 2,
    students: [
      makeStudent("stu-001", "Student Alpha"),
      makeStudent("stu-002", "Student Beta"),
    ],
    stability: "persistent",
    computed_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeGroupsResponse(
  groups: StudentGroupResponse[] = [makeGroup()],
): ClassGroupsResponse {
  return { class_id: CLASS_ID, groups };
}

function makeEnrolled(id: string, full_name: string): EnrolledStudentResponse {
  return {
    enrollment_id: `enr-${id}`,
    enrolled_at: "2026-01-01T00:00:00Z",
    student: {
      id,
      teacher_id: "teacher-001",
      full_name,
      external_id: null,
      teacher_notes: null,
      created_at: "2026-01-01T00:00:00Z",
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListStudents.mockResolvedValue([
    makeEnrolled("stu-001", "Student Alpha"),
    makeEnrolled("stu-002", "Student Beta"),
    makeEnrolled("stu-003", "Student Gamma"),
  ]);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SkillGroupsPanel — loading state", () => {
  it("shows loading skeleton while groups are fetching", () => {
    mockGetClassGroups.mockReturnValue(new Promise(() => {})); // never resolves
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });
    // Loading skeleton: aria-busy container with animated placeholders
    expect(document.querySelector("[aria-busy='true']")).toBeTruthy();
  });
});

describe("SkillGroupsPanel — error state", () => {
  it("shows error alert when fetch fails", async () => {
    mockGetClassGroups.mockRejectedValue(
      new ApiError("Server error", 500, "SERVER_ERROR"),
    );
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/failed to load skill groups/i);
  });
});

describe("SkillGroupsPanel — empty state", () => {
  it("shows empty state when no groups have been computed", async () => {
    mockGetClassGroups.mockResolvedValue(makeGroupsResponse([]));
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText(/no skill groups yet/i)).toBeInTheDocument();
    });
  });
});

describe("SkillGroupsPanel — group list rendering", () => {
  it("renders group name (label), skill key, and student count", async () => {
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([
        makeGroup({
          id: "grp-001",
          label: "Evidence",
          skill_key: "evidence",
          student_count: 2,
          stability: "persistent",
        }),
      ]),
    );
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Evidence")).toBeInTheDocument();
    });
    // skill_key rendered separately as "Skill gap: evidence"
    expect(screen.getAllByText(/evidence/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/2 students/i)).toBeInTheDocument();
  });

  it("renders stability badges", async () => {
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([
        makeGroup({ id: "grp-001", stability: "new", label: "Thesis" }),
        makeGroup({ id: "grp-002", stability: "persistent", label: "Evidence" }),
        makeGroup({
          id: "grp-003",
          stability: "exited",
          label: "Organization",
          students: [],
          student_count: 0,
        }),
      ]),
    );
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("New")).toBeInTheDocument();
      expect(screen.getByText("Persistent")).toBeInTheDocument();
      expect(screen.getByText("Resolved")).toBeInTheDocument();
    });
  });

  it("renders active and resolved groups in separate sections", async () => {
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([
        makeGroup({ id: "grp-001", stability: "persistent", label: "Evidence" }),
        makeGroup({
          id: "grp-002",
          stability: "exited",
          label: "Thesis",
          students: [],
          student_count: 0,
        }),
      ]),
    );
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/active groups/i)).toBeInTheDocument();
      expect(screen.getByText(/resolved groups/i)).toBeInTheDocument();
    });
  });
});

describe("SkillGroupsPanel — expand / collapse", () => {
  it("members are hidden by default (collapsed)", async () => {
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([makeGroup()]),
    );
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Evidence")).toBeInTheDocument();
    });
    // Student names should not be visible initially
    expect(screen.queryByText("Student Alpha")).not.toBeInTheDocument();
  });

  it("expand toggle reveals student members", async () => {
    const user = userEvent.setup();
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([makeGroup()]),
    );
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Evidence")).toBeInTheDocument();
    });

    const expandBtn = screen.getByRole("button", { name: /expand group/i });
    await user.click(expandBtn);

    await waitFor(() => {
      expect(screen.getByText("Student Alpha")).toBeInTheDocument();
      expect(screen.getByText("Student Beta")).toBeInTheDocument();
    });
  });

  it("shows add student selector when there are non-member enrolled students", async () => {
    const user = userEvent.setup();
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([makeGroup()]), // stu-001 and stu-002 are members
    );
    // stu-003 is enrolled but not in the group
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });

    await waitFor(() => screen.getByText("Evidence"));
    await user.click(screen.getByRole("button", { name: /expand group/i }));

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: /add student to evidence/i })).toBeInTheDocument();
    });
  });
});

describe("SkillGroupsPanel — manual adjustment", () => {
  it("remove button calls updateGroupMembers without the removed student", async () => {
    const user = userEvent.setup();
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([makeGroup()]),
    );
    mockUpdateGroupMembers.mockResolvedValue({
      ...makeGroup(),
      students: [makeStudent("stu-002", "Student Beta")],
      student_count: 1,
    });

    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });
    await waitFor(() => screen.getByText("Evidence"));

    // Expand the group
    await user.click(screen.getByRole("button", { name: /expand group/i }));
    await waitFor(() => screen.getByText("Student Alpha"));

    // Remove Student Alpha
    const removeBtn = screen.getByRole("button", { name: /remove Student Alpha from group/i });
    await user.click(removeBtn);

    await waitFor(() => {
      expect(mockUpdateGroupMembers).toHaveBeenCalledWith(
        CLASS_ID,
        "grp-001",
        { student_ids: ["stu-002"] }, // stu-001 removed
      );
    });
  });

  it("add student selector calls updateGroupMembers with the new student id appended", async () => {
    const user = userEvent.setup();
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([makeGroup()]),
    );
    mockUpdateGroupMembers.mockResolvedValue({
      ...makeGroup(),
      students: [
        makeStudent("stu-001", "Student Alpha"),
        makeStudent("stu-002", "Student Beta"),
        makeStudent("stu-003", "Student Gamma"),
      ],
      student_count: 3,
    });

    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });
    await waitFor(() => screen.getByText("Evidence"));
    await user.click(screen.getByRole("button", { name: /expand group/i }));

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: /add student to evidence/i })).toBeInTheDocument();
    });

    const select = screen.getByRole("combobox", { name: /add student to evidence/i });
    await user.selectOptions(select, "stu-003");

    await waitFor(() => {
      expect(mockUpdateGroupMembers).toHaveBeenCalledWith(
        CLASS_ID,
        "grp-001",
        { student_ids: ["stu-001", "stu-002", "stu-003"] },
      );
    });
  });

  it("exited groups do not show remove buttons", async () => {
    const user = userEvent.setup();
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([
        makeGroup({
          id: "grp-003",
          stability: "exited",
          label: "Thesis",
          students: [],
          student_count: 0,
        }),
      ]),
    );
    render(<SkillGroupsPanel classId={CLASS_ID} />, { wrapper });

    await waitFor(() => screen.getByText("Thesis"));
    await user.click(screen.getByRole("button", { name: /expand group/i }));

    // No remove buttons for exited groups
    expect(screen.queryByRole("button", { name: /remove .* from group/i })).not.toBeInTheDocument();
  });
});

describe("SkillGroupsPanel — heatmap cross-reference", () => {
  it("heatmap link calls onNavigateToHeatmap callback", async () => {
    const user = userEvent.setup();
    const onHeatmap = vi.fn();
    mockGetClassGroups.mockResolvedValue(
      makeGroupsResponse([makeGroup()]),
    );

    render(
      <SkillGroupsPanel classId={CLASS_ID} onNavigateToHeatmap={onHeatmap} />,
      { wrapper },
    );
    await waitFor(() => screen.getByText("Evidence"));

    const heatmapLink = screen.getByRole("button", { name: /view skill heatmap/i });
    await user.click(heatmapLink);

    expect(onHeatmap).toHaveBeenCalledTimes(1);
  });
});
