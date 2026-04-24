/**
 * Tests for RegradeQueue — M4.9 (Regrade request UI).
 *
 * Covers:
 * - Queue renders open regrade requests with student identifier, criterion, dispute text
 * - Empty state shown when no open requests exist
 * - Status filter buttons change the visible set
 * - Approve action calls resolveRegradeRequest with resolution "approved"
 * - Deny action is blocked (error shown) when resolution note is empty
 * - Deny action calls resolveRegradeRequest with resolution "denied" and note
 * - Resolve error messages are shown without PII
 * - Review panel opens when "Review" is clicked
 * - Review panel closes when close button is clicked
 * - Log request tab is shown
 * - Log request form shows essay selector and dispute text field
 * - Log request form blocks submission when dispute text is empty
 * - Log request calls createRegradeRequest on submit
 * - DISPUTE_TEXT_MAX_CHARS export is 500
 *
 * Note: Close-regrade-window tests are not included — the backend endpoint
 * does not yet exist, so the UI action is not rendered.
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and placeholder text only.
 * - No credential-format strings in test data.
 * - Error messages are static strings; raw server text never asserted.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — must come before component imports
// ---------------------------------------------------------------------------

const mockListRegradeRequests = vi.fn();
const mockCreateRegradeRequest = vi.fn();
const mockResolveRegradeRequest = vi.fn();
const mockGetGrade = vi.fn();

vi.mock("@/lib/api/regrade-requests", () => ({
  listRegradeRequests: (...args: unknown[]) =>
    mockListRegradeRequests(...args),
  createRegradeRequest: (...args: unknown[]) =>
    mockCreateRegradeRequest(...args),
  resolveRegradeRequest: (...args: unknown[]) =>
    mockResolveRegradeRequest(...args),
}));

vi.mock("@/lib/api/grades", () => ({
  getGrade: (...args: unknown[]) => mockGetGrade(...args),
}));

// ---------------------------------------------------------------------------
// Imports (after mocks)
// ---------------------------------------------------------------------------

import {
  RegradeQueue,
  DISPUTE_TEXT_MAX_CHARS,
} from "@/components/grading/RegradeQueue";
import type { RegradeRequest } from "@/lib/api/regrade-requests";
import type { EssayListItem } from "@/lib/api/essays";
import type { RubricSnapshotCriterion } from "@/components/grading/EssayReviewPanel";
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

const ASSIGNMENT_ID = "asgn-test-001";

/** Factory for RegradeRequest — no real student PII (FERPA). */
function makeRequest(
  overrides: Partial<RegradeRequest> & Pick<RegradeRequest, "id">,
): RegradeRequest {
  return {
    grade_id: "grade-aaaa-0001",
    criterion_score_id: null,
    teacher_id: "teacher-0001",
    dispute_text: "Test dispute justification",
    status: "open",
    resolution_note: null,
    resolved_at: null,
    created_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

/** Factory for EssayListItem — no real student data. */
function makeEssay(overrides: Partial<EssayListItem> = {}): EssayListItem {
  return {
    essay_id: "essay-test-001",
    assignment_id: ASSIGNMENT_ID,
    student_id: null,
    student_name: null,
    status: "graded",
    word_count: 400,
    submitted_at: "2026-04-01T00:00:00Z",
    auto_assign_status: null,
    ...overrides,
  };
}

const RUBRIC_CRITERIA: RubricSnapshotCriterion[] = [
  {
    id: "crit-001",
    name: "Thesis statement",
    description: "Clear and arguable thesis",
    weight: 0.4,
    min_score: 0,
    max_score: 10,
  },
  {
    id: "crit-002",
    name: "Evidence",
    description: "Relevant and properly cited evidence",
    weight: 0.6,
    min_score: 0,
    max_score: 10,
  },
];

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

describe("DISPUTE_TEXT_MAX_CHARS", () => {
  it("is 500", () => {
    expect(DISPUTE_TEXT_MAX_CHARS).toBe(500);
  });
});

// ---------------------------------------------------------------------------
// Queue renders
// ---------------------------------------------------------------------------

describe("RegradeQueue — queue tab renders", () => {
  beforeEach(() => {
    mockListRegradeRequests.mockReset();
    mockGetGrade.mockReset();
  });

  it("renders the section heading", async () => {
    mockListRegradeRequests.mockResolvedValue([]);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    expect(
      screen.getByRole("heading", { name: /regrade requests/i }),
    ).toBeInTheDocument();
  });

  it("shows the empty state when no open requests exist", async () => {
    mockListRegradeRequests.mockResolvedValue([]);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() => {
      expect(
        screen.getByText(/no open regrade requests/i),
      ).toBeInTheDocument();
    });
  });

  it("renders open requests with dispute text and criterion info", async () => {
    const req = makeRequest({
      id: "req-0001",
      dispute_text: "The score seems too low",
      criterion_score_id: null,
    });
    mockListRegradeRequests.mockResolvedValue([req]);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() => {
      expect(
        screen.getByText("The score seems too low"),
      ).toBeInTheDocument();
    });

    // The table should contain "Overall grade" for the criterion column.
    // (The criterion selector dropdown also has "Overall grade" as default option.)
    const table = screen.getByRole("table", { name: /regrade request queue/i });
    expect(within(table).getByText("Overall grade")).toBeInTheDocument();
  });

  it("shows 'Specific criterion' when criterion_score_id is set", async () => {
    const req = makeRequest({
      id: "req-0002",
      criterion_score_id: "cs-aaa-001",
    });
    mockListRegradeRequests.mockResolvedValue([req]);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() => {
      expect(screen.getByText("Specific criterion")).toBeInTheDocument();
    });
  });

  it("shows open badge count in heading", async () => {
    const requests = [
      makeRequest({ id: "req-0003", status: "open" }),
      makeRequest({ id: "req-0004", status: "approved" }),
    ];
    mockListRegradeRequests.mockResolvedValue(requests);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() => {
      expect(screen.getByText("1 open")).toBeInTheDocument();
    });
  });

  it("filters to resolved requests when 'Resolved' filter is clicked", async () => {
    const requests = [
      makeRequest({ id: "req-open", status: "open", dispute_text: "Open dispute" }),
      makeRequest({
        id: "req-approved",
        status: "approved",
        dispute_text: "Approved dispute",
      }),
    ];
    mockListRegradeRequests.mockResolvedValue(requests);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    // Wait for requests to load
    await waitFor(() =>
      expect(screen.getByText("Open dispute")).toBeInTheDocument(),
    );

    // Click "Resolved" filter
    await userEvent.click(screen.getByRole("button", { name: /^resolved$/i }));

    // Now we should see the approved one, not the open one
    expect(screen.queryByText("Open dispute")).not.toBeInTheDocument();
    expect(screen.getByText("Approved dispute")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Review panel — approve and deny
// ---------------------------------------------------------------------------

describe("RegradeQueue — review panel", () => {
  beforeEach(() => {
    mockListRegradeRequests.mockReset();
    mockResolveRegradeRequest.mockReset();
    mockGetGrade.mockReset();
  });

  it("opens the review panel when 'Review' is clicked", async () => {
    const req = makeRequest({ id: "req-panel-001" });
    mockListRegradeRequests.mockResolvedValue([req]);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /review regrade request/i })).toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: /review regrade request/i }),
    );

    expect(
      screen.getByRole("dialog", { name: /regrade request review/i }),
    ).toBeInTheDocument();
  });

  it("closes the review panel when close button is clicked", async () => {
    const req = makeRequest({ id: "req-close-001" });
    mockListRegradeRequests.mockResolvedValue([req]);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /review regrade request/i }),
      ).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /review regrade request/i }),
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /close review panel/i }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("approve calls resolveRegradeRequest with resolution 'approved'", async () => {
    const req = makeRequest({ id: "req-approve-001" });
    const resolved = { ...req, status: "approved" as const };
    mockListRegradeRequests.mockResolvedValue([req]);
    mockResolveRegradeRequest.mockResolvedValue(resolved);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /review regrade request/i }),
      ).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /review regrade request/i }),
    );

    // Click "Approve"
    await userEvent.click(screen.getByRole("button", { name: /^approve$/i }));

    // Click "Confirm approval"
    await userEvent.click(
      screen.getByRole("button", { name: /confirm approval/i }),
    );

    await waitFor(() => {
      expect(mockResolveRegradeRequest).toHaveBeenCalledWith(
        "req-approve-001",
        expect.objectContaining({ resolution: "approved" }),
      );
    });
  });

  it("deny is blocked when resolution note is empty", async () => {
    const req = makeRequest({ id: "req-deny-block-001" });
    mockListRegradeRequests.mockResolvedValue([req]);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /review regrade request/i }),
      ).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /review regrade request/i }),
    );

    // Click "Deny"
    await userEvent.click(screen.getByRole("button", { name: /^deny$/i }));

    // Click "Confirm denial" without entering a note
    await userEvent.click(
      screen.getByRole("button", { name: /confirm denial/i }),
    );

    // resolveRegradeRequest should NOT have been called
    expect(mockResolveRegradeRequest).not.toHaveBeenCalled();

    // Error message should be shown
    expect(
      screen.getByRole("alert"),
    ).toHaveTextContent(/resolution note is required/i);
  });

  it("deny calls resolveRegradeRequest with resolution 'denied' and note", async () => {
    const req = makeRequest({ id: "req-deny-001" });
    const resolved = {
      ...req,
      status: "denied" as const,
      resolution_note: "The score is accurate per the rubric criteria.",
    };
    mockListRegradeRequests.mockResolvedValue([req]);
    mockResolveRegradeRequest.mockResolvedValue(resolved);

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /review regrade request/i }),
      ).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /review regrade request/i }),
    );

    // Click "Deny"
    await userEvent.click(screen.getByRole("button", { name: /^deny$/i }));

    // Enter a resolution note
    await userEvent.type(
      screen.getByRole("textbox", { name: /resolution note/i }),
      "The score is accurate per the rubric criteria.",
    );

    // Click "Confirm denial"
    await userEvent.click(
      screen.getByRole("button", { name: /confirm denial/i }),
    );

    await waitFor(() => {
      expect(mockResolveRegradeRequest).toHaveBeenCalledWith(
        "req-deny-001",
        expect.objectContaining({
          resolution: "denied",
          resolution_note: "The score is accurate per the rubric criteria.",
        }),
      );
    });
  });

  it("shows an error message when resolve fails", async () => {
    const req = makeRequest({ id: "req-error-001" });
    mockListRegradeRequests.mockResolvedValue([req]);
    mockResolveRegradeRequest.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_SERVER_ERROR", message: "err" }),
    );

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /review regrade request/i }),
      ).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /review regrade request/i }),
    );

    await userEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await userEvent.click(
      screen.getByRole("button", { name: /confirm approval/i }),
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /failed to resolve the request/i,
      );
    });

    // Raw server error text must NOT be present
    expect(screen.queryByText("err")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Log request form
// ---------------------------------------------------------------------------

describe("RegradeQueue — log request form", () => {
  beforeEach(() => {
    mockListRegradeRequests.mockResolvedValue([]);
    mockCreateRegradeRequest.mockReset();
    mockGetGrade.mockReset();
  });

  it("renders the 'Log request' tab", async () => {
    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[makeEssay()]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    expect(
      screen.getByRole("tab", { name: /log request/i }),
    ).toBeInTheDocument();
  });

  it("switches to the log form when 'Log request' tab is clicked", async () => {
    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[makeEssay()]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("tab", { name: /log request/i }));

    expect(
      screen.getByRole("form", { name: /log regrade request/i }),
    ).toBeInTheDocument();
  });

  it("shows dispute text field with character counter", async () => {
    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[makeEssay()]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("tab", { name: /log request/i }));

    expect(
      screen.getByLabelText(/dispute justification/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/500 characters remaining/i)).toBeInTheDocument();
  });

  it("blocks submission when dispute text is empty", async () => {
    // Set grade mock before rendering so it resolves when the essay is selected.
    mockGetGrade.mockResolvedValue({
      id: "grade-test-001",
      criterion_scores: [],
    });

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[makeEssay({ student_name: null })]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("tab", { name: /log request/i }));

    // Select an essay — triggers grade fetch
    const essaySelect = screen.getByRole("combobox", { name: /essay/i });
    await userEvent.selectOptions(essaySelect, "essay-test-001");

    // Wait for grade data to load (criterion selector becomes enabled)
    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: /criterion/i }),
      ).not.toBeDisabled();
    });

    // Leave dispute text empty, click Submit
    await userEvent.click(
      screen.getByRole("button", { name: /submit request/i }),
    );

    expect(mockCreateRegradeRequest).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /dispute text is required/i,
      );
    });
  });

  it("calls createRegradeRequest on valid submission", async () => {
    const createdReq = makeRequest({
      id: "req-created-001",
      dispute_text: "Grade is incorrect",
    });
    mockCreateRegradeRequest.mockResolvedValue(createdReq);
    mockGetGrade.mockResolvedValue({
      id: "grade-test-001",
      criterion_scores: [
        { id: "cs-0001", rubric_criterion_id: "crit-001" },
      ],
    });

    render(
      <RegradeQueue
        assignmentId={ASSIGNMENT_ID}
        essays={[makeEssay()]}
        rubricCriteria={RUBRIC_CRITERIA}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("tab", { name: /log request/i }));

    const essaySelect = screen.getByRole("combobox", { name: /essay/i });
    await userEvent.selectOptions(essaySelect, "essay-test-001");

    // Wait for grade to load
    await waitFor(() =>
      expect(
        screen.queryByText(/loading/i),
      ).not.toBeInTheDocument(),
    );

    const disputeInput = screen.getByRole("textbox", {
      name: /dispute justification/i,
    });
    await userEvent.type(disputeInput, "Grade is incorrect");

    await userEvent.click(
      screen.getByRole("button", { name: /submit request/i }),
    );

    await waitFor(() => {
      expect(mockCreateRegradeRequest).toHaveBeenCalledWith(
        "grade-test-001",
        expect.objectContaining({ dispute_text: "Grade is incorrect" }),
      );
    });
  });
});
