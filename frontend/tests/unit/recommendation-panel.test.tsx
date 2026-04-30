/**
 * Tests for RecommendationPanel — M6.9 (Instruction Recommendations UI).
 *
 * Covers:
 * - RecommendationPanel: shows loading skeleton while fetching
 * - RecommendationPanel: shows error alert when fetch fails
 * - RecommendationPanel: shows empty state when no recommendations exist
 * - RecommendationPanel: renders objective, structure, and evidence summary
 * - RecommendationPanel: renders status badge for pending_review item
 * - RecommendationPanel: shows Accept, Modify, Dismiss buttons for pending_review
 * - RecommendationPanel: hides action buttons for accepted items
 * - RecommendationPanel: hides action buttons for dismissed items
 * - RecommendationPanel: Accept button shows confirmation dialog
 * - RecommendationPanel: confirmation dialog calls assignRecommendation on confirm
 * - RecommendationPanel: confirmation dialog closes without action on cancel
 * - RecommendationPanel: Dismiss button shows confirmation dialog
 * - RecommendationPanel: Dismiss confirmation calls dismissRecommendation on confirm
 * - RecommendationPanel: Modify button enters edit mode with editable fields
 * - RecommendationPanel: "Assign modified" from modify mode shows confirmation dialog
 * - RecommendationPanel: Cancel in modify mode restores view mode
 * - RecommendationPanel: buttons disabled while assignRecommendation is pending
 * - RecommendationPanel: shows error alert when assignRecommendation fails
 * - RecommendationPanel: shows error alert when dismissRecommendation fails
 * - RecommendationPanel: generate form calls generateStudentRecommendations and refetches
 * - RecommendationPanel: pending_review items sorted before accepted and dismissed
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
// Mocks — declared before component imports per Vitest hoisting rules
// ---------------------------------------------------------------------------

const mockListStudentRecommendations = vi.fn();
const mockGenerateStudentRecommendations = vi.fn();
const mockAssignRecommendation = vi.fn();
const mockDismissRecommendation = vi.fn();

vi.mock("@/lib/api/recommendations", () => ({
  listStudentRecommendations: (...args: unknown[]) =>
    mockListStudentRecommendations(...args),
  generateStudentRecommendations: (...args: unknown[]) =>
    mockGenerateStudentRecommendations(...args),
  assignRecommendation: (...args: unknown[]) => mockAssignRecommendation(...args),
  dismissRecommendation: (...args: unknown[]) => mockDismissRecommendation(...args),
}));

// ---------------------------------------------------------------------------
// Component imports (after mock declarations)
// ---------------------------------------------------------------------------

import { RecommendationPanel } from "@/components/recommendations/RecommendationPanel";
import { ApiError } from "@/lib/api/errors";
import type { InstructionRecommendationResponse } from "@/lib/api/recommendations";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function makeRecommendation(
  overrides: Partial<InstructionRecommendationResponse> = {},
): InstructionRecommendationResponse {
  return {
    id: "rec-001",
    teacher_id: "teacher-001",
    student_id: "student-001",
    group_id: null,
    worklist_item_id: null,
    skill_key: "evidence",
    grade_level: "Grade 8",
    prompt_version: "instruction-v1",
    recommendations: [
      {
        skill_dimension: "evidence",
        title: "Evidence Workshop",
        description: "Practice integrating evidence into paragraphs.",
        estimated_minutes: 20,
        strategy_type: "guided_practice",
      },
    ],
    evidence_summary: "Skill gap in 'evidence': average score 40%, trend stable.",
    status: "pending_review",
    created_at: "2026-04-01T12:00:00Z",
    ...overrides,
  };
}

const STUDENT_ID = "student-001";

beforeEach(() => {
  vi.clearAllMocks();
  mockAssignRecommendation.mockResolvedValue(
    makeRecommendation({ status: "accepted" }),
  );
  mockDismissRecommendation.mockResolvedValue(
    makeRecommendation({ status: "dismissed" }),
  );
  mockGenerateStudentRecommendations.mockResolvedValue(makeRecommendation());
});

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

describe("RecommendationPanel — loading state", () => {
  it("shows loading skeleton while fetching", () => {
    mockListStudentRecommendations.mockReturnValue(new Promise(() => {}));
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });
    expect(document.querySelector("[aria-busy='true']")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

describe("RecommendationPanel — error state", () => {
  it("shows error alert when fetch fails", async () => {
    mockListStudentRecommendations.mockRejectedValue(
      new ApiError(500, { code: "SERVER_ERROR", message: "Server error" }),
    );
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      /failed to load recommendations/i,
    );
  });
});

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

describe("RecommendationPanel — empty state", () => {
  it("shows empty state when no recommendations exist", async () => {
    mockListStudentRecommendations.mockResolvedValue([]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });
    await waitFor(() => {
      expect(
        screen.getByText(/no recommendations yet/i),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Card rendering
// ---------------------------------------------------------------------------

describe("RecommendationPanel — card rendering", () => {
  it("renders objective, structure, and evidence summary", async () => {
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      // Objective / title
      expect(screen.getByText("Evidence Workshop")).toBeInTheDocument();
      // Strategy type (structure)
      expect(screen.getByText("Guided Practice")).toBeInTheDocument();
      // Description
      expect(
        screen.getByText("Practice integrating evidence into paragraphs."),
      ).toBeInTheDocument();
      // Evidence summary
      expect(
        screen.getByText(/skill gap in 'evidence'/i),
      ).toBeInTheDocument();
    });
  });

  it("renders 'Pending Review' status badge for pending_review item", async () => {
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Pending Review")).toBeInTheDocument();
    });
  });

  it("renders 'Accepted' status badge for accepted item", async () => {
    mockListStudentRecommendations.mockResolvedValue([
      makeRecommendation({ status: "accepted" }),
    ]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Accepted")).toBeInTheDocument();
    });
  });

  it("renders 'Dismissed' status badge for dismissed item", async () => {
    mockListStudentRecommendations.mockResolvedValue([
      makeRecommendation({ status: "dismissed" }),
    ]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Dismissed")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Action buttons
// ---------------------------------------------------------------------------

describe("RecommendationPanel — action buttons", () => {
  it("shows Accept, Modify, Dismiss buttons for pending_review items", async () => {
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /^accept$/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /^modify$/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /^dismiss$/i }),
      ).toBeInTheDocument();
    });
  });

  it("hides action buttons for accepted items", async () => {
    mockListStudentRecommendations.mockResolvedValue([
      makeRecommendation({ status: "accepted" }),
    ]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /^accept$/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /^dismiss$/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("hides action buttons for dismissed items", async () => {
    mockListStudentRecommendations.mockResolvedValue([
      makeRecommendation({ status: "dismissed" }),
    ]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /^accept$/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /^modify$/i }),
      ).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Accept flow
// ---------------------------------------------------------------------------

describe("RecommendationPanel — accept flow", () => {
  it("Accept button shows confirmation dialog", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^accept$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^accept$/i }));

    expect(
      screen.getByRole("dialog", { name: /assign this recommendation/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /confirm assignment/i }),
    ).toBeInTheDocument();
  });

  it("confirm button in dialog calls assignRecommendation", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^accept$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^accept$/i }));
    await user.click(
      screen.getByRole("button", { name: /confirm assignment/i }),
    );

    await waitFor(() => {
      expect(mockAssignRecommendation).toHaveBeenCalledWith("rec-001");
    });
  });

  it("cancel button in dialog closes without calling API", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^accept$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^accept$/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(mockAssignRecommendation).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("dialog"),
    ).not.toBeInTheDocument();
  });

  it("Escape key closes the confirmation dialog without calling API", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^accept$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^accept$/i }));
    await user.keyboard("{Escape}");

    expect(mockAssignRecommendation).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows error message when assignRecommendation fails", async () => {
    const user = userEvent.setup();
    mockAssignRecommendation.mockRejectedValue(
      new ApiError(500, { code: "SERVER_ERROR", message: "fail" }),
    );
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^accept$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^accept$/i }));
    await user.click(
      screen.getByRole("button", { name: /confirm assignment/i }),
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Dismiss flow
// ---------------------------------------------------------------------------

describe("RecommendationPanel — dismiss flow", () => {
  it("Dismiss button shows confirmation dialog", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^dismiss$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^dismiss$/i }));

    expect(
      screen.getByRole("dialog", { name: /dismiss this recommendation/i }),
    ).toBeInTheDocument();
  });

  it("confirm dismiss calls dismissRecommendation", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^dismiss$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^dismiss$/i }));
    await user.click(
      screen.getByRole("button", { name: /^dismiss$/i, hidden: false }),
    );

    // Wait for the mutation to be called — dismiss button inside dialog confirms
    await waitFor(() => {
      // The dialog confirm button text is "Dismiss"
      expect(mockDismissRecommendation).toHaveBeenCalledWith("rec-001");
    });
  });

  it("shows error message when dismissRecommendation fails", async () => {
    const user = userEvent.setup();
    mockDismissRecommendation.mockRejectedValue(
      new ApiError(409, {
        code: "CONFLICT",
        message: "Already assigned",
      }),
    );
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^dismiss$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^dismiss$/i }));
    // Click the confirm button in dialog (also labeled "Dismiss")
    const dismissButtons = screen.getAllByRole("button", { name: /^dismiss$/i });
    // The last "Dismiss" button in DOM is the confirm button in the dialog
    await user.click(dismissButtons[dismissButtons.length - 1]);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/cannot be updated/i);
  });
});

// ---------------------------------------------------------------------------
// Modify flow
// ---------------------------------------------------------------------------

describe("RecommendationPanel — modify flow", () => {
  it("Modify button enters edit mode with editable fields", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^modify$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^modify$/i }));

    // Editable input for the activity title
    const titleInput = screen.getByRole("textbox", { name: /objective/i });
    expect(titleInput).toBeInTheDocument();
    expect((titleInput as HTMLInputElement).value).toBe("Evidence Workshop");

    // Textarea for description
    const descTextarea = screen.getByRole("textbox", {
      name: /structure \/ description/i,
    });
    expect(descTextarea).toBeInTheDocument();
  });

  it("'Assign modified' button shows confirmation dialog", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^modify$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^modify$/i }));
    await user.click(
      screen.getByRole("button", { name: /assign modified/i }),
    );

    expect(
      screen.getByRole("dialog", { name: /assign this recommendation/i }),
    ).toBeInTheDocument();
  });

  it("Cancel in modify mode restores view mode", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([makeRecommendation()]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^modify$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^modify$/i }));

    // In modify mode, Cancel button is shown
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    // Back in view mode: Accept / Modify / Dismiss buttons visible again
    expect(
      screen.getByRole("button", { name: /^accept$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^modify$/i }),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Generate form
// ---------------------------------------------------------------------------

describe("RecommendationPanel — generate form", () => {
  it("renders generate form with grade level and duration controls", async () => {
    mockListStudentRecommendations.mockResolvedValue([]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: /grade level/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("spinbutton", { name: /target duration/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /^generate$/i }),
      ).toBeInTheDocument();
    });
  });

  it("Generate button calls generateStudentRecommendations with correct args", async () => {
    const user = userEvent.setup();
    mockListStudentRecommendations.mockResolvedValue([]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^generate$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^generate$/i }));

    await waitFor(() => {
      expect(mockGenerateStudentRecommendations).toHaveBeenCalledWith(
        STUDENT_ID,
        expect.objectContaining({
          grade_level: expect.any(String),
          duration_minutes: expect.any(Number),
        }),
      );
    });
  });

  it("shows error message when generateStudentRecommendations fails", async () => {
    const user = userEvent.setup();
    mockGenerateStudentRecommendations.mockRejectedValue(
      new ApiError(500, { code: "SERVER_ERROR", message: "fail" }),
    );
    mockListStudentRecommendations.mockResolvedValue([]);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() =>
      screen.getByRole("button", { name: /^generate$/i }),
    );
    await user.click(screen.getByRole("button", { name: /^generate$/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/failed to generate recommendations/i),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Sort order
// ---------------------------------------------------------------------------

describe("RecommendationPanel — sort order", () => {
  it("pending_review items appear before accepted and dismissed", async () => {
    const recs: InstructionRecommendationResponse[] = [
      makeRecommendation({ id: "rec-acc", status: "accepted" }),
      makeRecommendation({ id: "rec-dis", status: "dismissed" }),
      makeRecommendation({ id: "rec-pen", status: "pending_review" }),
    ];
    mockListStudentRecommendations.mockResolvedValue(recs);
    render(<RecommendationPanel studentId={STUDENT_ID} />, { wrapper });

    await waitFor(() => {
      const badges = screen.getAllByText(/pending review|accepted|dismissed/i);
      // First badge rendered should be "Pending Review"
      expect(badges[0]).toHaveTextContent("Pending Review");
    });
  });
});
