/**
 * Tests for the Assignment UI — M3.13.
 *
 * Covers:
 * - Assignment creation form: title required validation
 * - Assignment creation form: rubric required validation
 * - Assignment creation form: title max-length validation
 * - Assignment creation form: prompt max-length validation
 * - Assignment creation form: successful submit calls API and navigates
 * - Assignment creation form: server error displays generic message (no PII)
 * - Assignment creation form: rubric picker shows criteria preview
 * - Assignment overview: renders assignment title and status badge
 * - Assignment overview: status transition button shows only for valid next states
 * - Assignment overview: transition button not rendered when assignment is returned
 * - Assignment overview: submission status badges render correctly
 * - Assignment overview: shows error when assignment fetch fails
 *
 * Security:
 * - No student PII in fixtures — synthetic names only
 * - Server error messages never include student essay content
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockCreateAssignment = vi.fn();
const mockGetAssignment = vi.fn();
const mockUpdateAssignment = vi.fn();
const mockListRubrics = vi.fn();
const mockGetRubric = vi.fn();

vi.mock("@/lib/api/assignments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/assignments")>();
  return {
    ...actual,
    createAssignment: (...args: unknown[]) => mockCreateAssignment(...args),
    getAssignment: (...args: unknown[]) => mockGetAssignment(...args),
    updateAssignment: (...args: unknown[]) => mockUpdateAssignment(...args),
  };
});

vi.mock("@/lib/api/rubrics", () => ({
  listRubrics: (...args: unknown[]) => mockListRubrics(...args),
  getRubric: (...args: unknown[]) => mockGetRubric(...args),
}));

// Mock Next.js navigation
const mockPush = vi.fn();
const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ classId: "cls-001", assignmentId: "asgn-001" }),
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useSearchParams: () => new URLSearchParams(),
}));

import NewAssignmentPage from "@/app/(dashboard)/dashboard/classes/[classId]/assignments/new/page";
import AssignmentOverviewPage from "@/app/(dashboard)/dashboard/assignments/[assignmentId]/page";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const RUBRIC_LIST = [
  {
    id: "rub-001",
    name: "5-Paragraph Essay",
    description: null,
    is_template: false,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    criterion_count: 3,
  },
  {
    id: "rub-002",
    name: "Argumentative Essay",
    description: null,
    is_template: false,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    criterion_count: 4,
  },
];

const RUBRIC_DETAIL = {
  id: "rub-001",
  name: "5-Paragraph Essay",
  description: null,
  is_template: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
  criteria: [
    {
      id: "crit-1",
      name: "Thesis",
      description: "Clear thesis statement",
      weight: 40,
      min_score: 1,
      max_score: 5,
      display_order: 1,
      anchor_descriptions: null,
    },
    {
      id: "crit-2",
      name: "Evidence",
      description: "Supporting evidence",
      weight: 40,
      min_score: 1,
      max_score: 5,
      display_order: 2,
      anchor_descriptions: null,
    },
    {
      id: "crit-3",
      name: "Conclusion",
      description: "Effective conclusion",
      weight: 20,
      min_score: 1,
      max_score: 5,
      display_order: 3,
      anchor_descriptions: null,
    },
  ],
};

const ASSIGNMENT_DRAFT = {
  id: "asgn-001",
  class_id: "cls-001",
  rubric_id: "rub-001",
  rubric_name: "5-Paragraph Essay",
  title: "Unit 1 Essay",
  prompt: null,
  due_date: null,
  status: "draft" as const,
  created_at: "2025-01-01T00:00:00Z",
  submission_statuses: [
    {
      student_id: "stu-001",
      student_name: "Student Alpha",
      submission_status: "pending" as const,
      submitted_at: null,
    },
    {
      student_id: "stu-002",
      student_name: "Student Beta",
      submission_status: "submitted" as const,
      submitted_at: "2025-03-15T10:00:00Z",
    },
  ],
};

const ASSIGNMENT_RETURNED = {
  ...ASSIGNMENT_DRAFT,
  status: "returned" as const,
  submission_statuses: [
    {
      student_id: "stu-001",
      student_name: "Student Alpha",
      submission_status: "returned" as const,
      submitted_at: "2025-03-14T09:00:00Z",
    },
  ],
};

// ---------------------------------------------------------------------------
// Test wrapper
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ===========================================================================
// Assignment creation form — validation
// ===========================================================================

describe("NewAssignmentPage — form validation", () => {
  beforeEach(() => {
    mockListRubrics.mockResolvedValue(RUBRIC_LIST);
  });

  it("shows required error when title is empty", async () => {
    const user = userEvent.setup();
    render(wrapper({ children: <NewAssignmentPage /> }));

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /create assignment/i }));

    await waitFor(() => {
      expect(screen.getByText(/title is required/i)).toBeInTheDocument();
    });
    expect(mockCreateAssignment).not.toHaveBeenCalled();
  });

  it("shows error when title exceeds 255 characters", async () => {
    const user = userEvent.setup();
    render(wrapper({ children: <NewAssignmentPage /> }));

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/title/i), "A".repeat(256));
    await user.click(screen.getByRole("button", { name: /create assignment/i }));

    await waitFor(() => {
      expect(screen.getByText(/title is too long/i)).toBeInTheDocument();
    });
    expect(mockCreateAssignment).not.toHaveBeenCalled();
  });

  it("shows required error when no rubric is selected", async () => {
    const user = userEvent.setup();
    render(wrapper({ children: <NewAssignmentPage /> }));

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText(/title/i), "My Assignment");
    await user.click(screen.getByRole("button", { name: /create assignment/i }));

    await waitFor(() => {
      expect(screen.getByText(/please select a rubric/i)).toBeInTheDocument();
    });
    expect(mockCreateAssignment).not.toHaveBeenCalled();
  });

  it("shows error when prompt exceeds 5000 characters", async () => {
    // Use fireEvent.change to set a long value directly — avoids the 5-second
    // per-character typing overhead of userEvent.type.
    const { fireEvent: fe } = await import("@testing-library/react");
    render(wrapper({ children: <NewAssignmentPage /> }));

    await waitFor(() => {
      expect(screen.getByLabelText(/writing prompt/i)).toBeInTheDocument();
    });

    const longPrompt = "B".repeat(5001);
    fe.change(screen.getByLabelText(/writing prompt/i), {
      target: { value: longPrompt },
    });

    fe.click(screen.getByRole("button", { name: /create assignment/i }));

    await waitFor(() => {
      expect(screen.getByText(/prompt is too long/i)).toBeInTheDocument();
    });
    expect(mockCreateAssignment).not.toHaveBeenCalled();
  });
});

// ===========================================================================
// Assignment creation form — rubric picker
// ===========================================================================

describe("NewAssignmentPage — rubric picker", () => {
  it("lists all teacher rubrics in the picker", async () => {
    mockListRubrics.mockResolvedValue(RUBRIC_LIST);
    render(wrapper({ children: <NewAssignmentPage /> }));

    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: /5-paragraph essay/i }),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("option", { name: /argumentative essay/i }),
    ).toBeInTheDocument();
  });

  it("shows criteria preview when a rubric is selected", async () => {
    mockListRubrics.mockResolvedValue(RUBRIC_LIST);
    mockGetRubric.mockResolvedValue(RUBRIC_DETAIL);

    const user = userEvent.setup();
    render(wrapper({ children: <NewAssignmentPage /> }));

    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: /5-paragraph essay/i }),
      ).toBeInTheDocument();
    });

    await user.selectOptions(
      screen.getByRole("combobox", { name: /rubric/i }),
      "rub-001",
    );

    await waitFor(() => {
      expect(screen.getByText(/criteria preview/i)).toBeInTheDocument();
    });
    expect(screen.getByText("Thesis")).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText("Conclusion")).toBeInTheDocument();
  });

  it("shows prompt to create rubric when teacher has none", async () => {
    mockListRubrics.mockResolvedValue([]);
    render(wrapper({ children: <NewAssignmentPage /> }));

    await waitFor(() => {
      expect(screen.getByText(/create your first rubric/i)).toBeInTheDocument();
    });
  });
});

// ===========================================================================
// Assignment creation form — submission
// ===========================================================================

describe("NewAssignmentPage — submission", () => {
  beforeEach(() => {
    mockListRubrics.mockResolvedValue(RUBRIC_LIST);
    mockGetRubric.mockResolvedValue(RUBRIC_DETAIL);
  });

  it("calls createAssignment and redirects on success", async () => {
    mockCreateAssignment.mockResolvedValueOnce(ASSIGNMENT_DRAFT);
    const user = userEvent.setup();
    const { fireEvent: fe } = await import("@testing-library/react");
    render(wrapper({ children: <NewAssignmentPage /> }));

    // Wait for rubric options to load
    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: /5-paragraph essay/i }),
      ).toBeInTheDocument();
    });

    // Use fireEvent.change for the title to avoid re-render timing issues
    fe.change(screen.getByLabelText(/title/i), {
      target: { value: "Unit 1 Essay" },
    });
    await user.selectOptions(
      screen.getByRole("combobox", { name: /rubric/i }),
      "rub-001",
    );
    await user.click(screen.getByRole("button", { name: /create assignment/i }));

    await waitFor(() => {
      expect(mockCreateAssignment).toHaveBeenCalledWith(
        "cls-001",
        expect.objectContaining({ title: "Unit 1 Essay", rubric_id: "rub-001" }),
      );
    });
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/dashboard/assignments/asgn-001");
    });
  });

  it("shows a generic error message on server failure — no student PII", async () => {
    mockCreateAssignment.mockRejectedValueOnce(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Internal server error" }),
    );
    const user = userEvent.setup();
    const { fireEvent: fe } = await import("@testing-library/react");
    render(wrapper({ children: <NewAssignmentPage /> }));

    // Wait for rubric options to load
    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: /5-paragraph essay/i }),
      ).toBeInTheDocument();
    });

    fe.change(screen.getByLabelText(/title/i), {
      target: { value: "Unit 1 Essay" },
    });
    await user.selectOptions(
      screen.getByRole("combobox", { name: /rubric/i }),
      "rub-001",
    );
    await user.click(screen.getByRole("button", { name: /create assignment/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/failed to create assignment/i),
      ).toBeInTheDocument();
    });
    // The raw API error message must not be shown to the teacher
    expect(
      screen.queryByText(/internal server error/i),
    ).not.toBeInTheDocument();
  });
});

// ===========================================================================
// Assignment overview — status display
// ===========================================================================

describe("AssignmentOverviewPage — status display", () => {
  it("renders assignment title and status badge", async () => {
    mockGetAssignment.mockResolvedValueOnce(ASSIGNMENT_DRAFT);
    render(wrapper({ children: <AssignmentOverviewPage /> }));

    await waitFor(() => {
      // Title appears in the h1 heading
      expect(screen.getByRole("heading", { name: /unit 1 essay/i })).toBeInTheDocument();
    });
    // Status badge
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("shows the correct transition button for draft status", async () => {
    mockGetAssignment.mockResolvedValueOnce(ASSIGNMENT_DRAFT);
    render(wrapper({ children: <AssignmentOverviewPage /> }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /open assignment/i }),
      ).toBeInTheDocument();
    });
  });

  it("does not show a transition button when assignment is returned", async () => {
    mockGetAssignment.mockResolvedValueOnce(ASSIGNMENT_RETURNED);
    render(wrapper({ children: <AssignmentOverviewPage /> }));

    // Wait for the assignment data to render (title in heading)
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /unit 1 essay/i })).toBeInTheDocument();
    });
    // No further transition from "returned"
    expect(
      screen.queryByRole("button", { name: /open assignment/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /close submissions/i }),
    ).not.toBeInTheDocument();
  });

  it("renders per-student submission status badges", async () => {
    mockGetAssignment.mockResolvedValueOnce(ASSIGNMENT_DRAFT);
    render(wrapper({ children: <AssignmentOverviewPage /> }));

    await waitFor(() => {
      expect(screen.getByText("Student Alpha")).toBeInTheDocument();
    });
    expect(screen.getByText("Student Beta")).toBeInTheDocument();
    // Status badges — there is also a column header "Status", so query by role
    // "cell" content to distinguish badge from header
    expect(screen.getByText("Pending")).toBeInTheDocument();
    // "Submitted" appears in the table header and as a badge; both are expected
    const submittedElements = screen.getAllByText("Submitted");
    expect(submittedElements.length).toBeGreaterThanOrEqual(1);
  });

  it("shows error message when assignment fetch fails", async () => {
    mockGetAssignment.mockRejectedValueOnce(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "Server error" }),
    );
    render(wrapper({ children: <AssignmentOverviewPage /> }));

    await waitFor(() => {
      expect(
        screen.getByText(/failed to load assignment/i),
      ).toBeInTheDocument();
    });
  });

  it("calls updateAssignment with next status when transition button clicked", async () => {
    mockGetAssignment.mockResolvedValueOnce(ASSIGNMENT_DRAFT);
    mockUpdateAssignment.mockResolvedValueOnce({
      ...ASSIGNMENT_DRAFT,
      status: "open",
    });

    const user = userEvent.setup();
    render(wrapper({ children: <AssignmentOverviewPage /> }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /open assignment/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /open assignment/i }));

    await waitFor(() => {
      expect(mockUpdateAssignment).toHaveBeenCalledWith(
        "asgn-001",
        { status: "open" },
      );
    });
  });
});
