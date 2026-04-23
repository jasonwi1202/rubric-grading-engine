/**
 * Tests for EssayReviewPanel — M3.21 (Essay review interface, core).
 *
 * Covers:
 * - computeTotalScore: live score recalculation with and without local overrides
 * - Locked state: all edit controls disabled when is_locked=true
 * - Unlocked state: all edit controls enabled when is_locked=false
 * - Score input visible with correct min/max constraints
 * - Lock button disabled when is_locked=true
 * - Lock button enabled (and clickable) when is_locked=false
 * - Clicking "Lock grade" calls lockGrade with the grade ID
 * - Summary feedback textarea disabled when locked
 * - Per-criterion feedback textarea disabled when locked
 * - Score input change triggers local total recalculation
 * - Save-error message shown on mutation failure (static string, no PII)
 * - Lock-error message shown on lock mutation failure (static string, no PII)
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs only.
 * - No credential-format strings in test data.
 * - Error assertions verify static UI strings, not raw server messages.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — must come before component imports
// ---------------------------------------------------------------------------

const mockOverrideCriterionScore = vi.fn();
const mockUpdateFeedback = vi.fn();
const mockLockGrade = vi.fn();

vi.mock("@/lib/api/grades", () => ({
  overrideCriterionScore: (...args: unknown[]) =>
    mockOverrideCriterionScore(...args),
  updateFeedback: (...args: unknown[]) => mockUpdateFeedback(...args),
  lockGrade: (...args: unknown[]) => mockLockGrade(...args),
}));

import {
  EssayReviewPanel,
  computeTotalScore,
  type RubricSnapshotCriterion,
} from "@/components/grading/EssayReviewPanel";
import type {
  GradeResponse,
  CriterionScoreResponse,
} from "@/lib/api/grades";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/** Wrap components in a fresh QueryClient for each test. */
function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Factory for a CriterionScoreResponse. No real student data. */
function makeCriterionScore(
  overrides: Partial<CriterionScoreResponse> &
    Pick<CriterionScoreResponse, "id" | "rubric_criterion_id">,
): CriterionScoreResponse {
  return {
    ai_score: 3,
    teacher_score: null,
    final_score: 3,
    ai_justification: "Synthetic AI justification for testing.",
    ai_feedback: null,
    teacher_feedback: null,
    confidence: "medium",
    created_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

/** Factory for a RubricSnapshotCriterion. */
function makeCriterion(
  overrides: Partial<RubricSnapshotCriterion> &
    Pick<RubricSnapshotCriterion, "id" | "name">,
): RubricSnapshotCriterion {
  return {
    description: "Synthetic criterion for testing.",
    weight: 25,
    min_score: 1,
    max_score: 5,
    ...overrides,
  };
}

/** Factory for a full GradeResponse. No real student data. */
function makeGrade(overrides: Partial<GradeResponse> = {}): GradeResponse {
  const cs1 = makeCriterionScore({
    id: "cs-test-001",
    rubric_criterion_id: "crit-test-001",
    final_score: 3,
  });
  const cs2 = makeCriterionScore({
    id: "cs-test-002",
    rubric_criterion_id: "crit-test-002",
    ai_score: 4,
    final_score: 4,
  });
  return {
    id: "grade-test-001",
    essay_version_id: "ev-test-001",
    total_score: "7",
    max_possible_score: "10",
    summary_feedback: "Synthetic AI summary feedback.",
    summary_feedback_edited: null,
    strictness: "balanced",
    ai_model: "test-model",
    prompt_version: "test-v1",
    is_locked: false,
    locked_at: null,
    overall_confidence: "high",
    created_at: "2026-04-01T00:00:00Z",
    criterion_scores: [cs1, cs2],
    ...overrides,
  };
}

const CRITERIA: RubricSnapshotCriterion[] = [
  makeCriterion({ id: "crit-test-001", name: "Thesis" }),
  makeCriterion({ id: "crit-test-002", name: "Evidence" }),
];

// ---------------------------------------------------------------------------
// computeTotalScore — pure function unit tests
// ---------------------------------------------------------------------------

describe("computeTotalScore", () => {
  const cs1 = makeCriterionScore({
    id: "cs-aaa-001",
    rubric_criterion_id: "crit-001",
    final_score: 3,
  });
  const cs2 = makeCriterionScore({
    id: "cs-bbb-002",
    rubric_criterion_id: "crit-002",
    final_score: 4,
  });

  it("returns the sum of final_scores when there are no local overrides", () => {
    expect(computeTotalScore([cs1, cs2], {})).toBe(7);
  });

  it("uses the local override instead of final_score when present", () => {
    // Override cs1 from 3 → 5
    expect(computeTotalScore([cs1, cs2], { "cs-aaa-001": 5 })).toBe(9);
  });

  it("handles multiple overrides simultaneously", () => {
    expect(
      computeTotalScore([cs1, cs2], { "cs-aaa-001": 5, "cs-bbb-002": 2 }),
    ).toBe(7);
  });

  it("returns 0 for an empty criterion list", () => {
    expect(computeTotalScore([], {})).toBe(0);
  });

  it("returns final_score when the override map has keys for other criteria only", () => {
    // Override for a criterion NOT in the list — should be ignored
    expect(
      computeTotalScore([cs1], { "cs-zzz-999": 5 }),
    ).toBe(3);
  });

  it("handles override value of 0 (falsy but valid)", () => {
    // Override to 0 — should use 0, not fall back to final_score
    expect(computeTotalScore([cs1], { "cs-aaa-001": 0 })).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// EssayReviewPanel — locked state
// ---------------------------------------------------------------------------

describe("EssayReviewPanel — locked state (is_locked=true)", () => {
  const lockedGrade = makeGrade({ is_locked: true, locked_at: "2026-04-10T12:00:00Z" });

  it("disables all score inputs when is_locked=true", async () => {
    render(
      <EssayReviewPanel
        grade={lockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    // All number inputs should be disabled
    const scoreInputs = screen.getAllByRole("spinbutton");
    for (const input of scoreInputs) {
      expect(input).toBeDisabled();
    }
  });

  it("disables all feedback textareas when is_locked=true", async () => {
    render(
      <EssayReviewPanel
        grade={lockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const textareas = screen.getAllByRole("textbox");
    for (const textarea of textareas) {
      expect(textarea).toBeDisabled();
    }
  });

  it("disables the lock button when is_locked=true", async () => {
    render(
      <EssayReviewPanel
        grade={lockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const lockBtn = screen.getByRole("button", { name: /grade is already locked/i });
    expect(lockBtn).toBeDisabled();
  });

  it("shows 'Grade locked' text on the lock button when is_locked=true", () => {
    render(
      <EssayReviewPanel
        grade={lockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    expect(
      screen.getByRole("button", { name: /grade is already locked/i }),
    ).toHaveTextContent("Grade locked");
  });

  it("shows a 'Locked' badge when is_locked=true", () => {
    render(
      <EssayReviewPanel
        grade={lockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.getByLabelText("This grade is locked")).toBeInTheDocument();
  });

  it("controls are not just hidden — they are functionally disabled", () => {
    render(
      <EssayReviewPanel
        grade={lockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    // Verify inputs exist in the DOM (not hidden) but are disabled
    const scoreInputs = screen.getAllByRole("spinbutton");
    expect(scoreInputs.length).toBeGreaterThan(0);
    for (const input of scoreInputs) {
      expect(input).toBeInTheDocument(); // not hidden
      expect(input).toBeDisabled();       // functionally disabled
    }
  });
});

// ---------------------------------------------------------------------------
// EssayReviewPanel — unlocked state
// ---------------------------------------------------------------------------

describe("EssayReviewPanel — unlocked state (is_locked=false)", () => {
  const unlockedGrade = makeGrade({ is_locked: false });

  beforeEach(() => {
    vi.clearAllMocks();
    mockOverrideCriterionScore.mockResolvedValue(unlockedGrade);
    mockUpdateFeedback.mockResolvedValue(unlockedGrade);
    mockLockGrade.mockResolvedValue({ ...unlockedGrade, is_locked: true });
  });

  it("enables all score inputs when is_locked=false", () => {
    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const scoreInputs = screen.getAllByRole("spinbutton");
    for (const input of scoreInputs) {
      expect(input).not.toBeDisabled();
    }
  });

  it("enables all feedback textareas when is_locked=false", () => {
    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const textareas = screen.getAllByRole("textbox");
    for (const textarea of textareas) {
      expect(textarea).not.toBeDisabled();
    }
  });

  it("enables the lock button when is_locked=false", () => {
    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const lockBtn = screen.getByRole("button", {
      name: /lock this grade as final/i,
    });
    expect(lockBtn).not.toBeDisabled();
  });

  it("calls lockGrade with the grade ID when the lock button is clicked", async () => {
    const user = userEvent.setup();
    const onGradeUpdate = vi.fn();

    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={onGradeUpdate}
      />,
      { wrapper },
    );

    const lockBtn = screen.getByRole("button", {
      name: /lock this grade as final/i,
    });
    await user.click(lockBtn);

    await waitFor(() =>
      expect(mockLockGrade).toHaveBeenCalledWith(unlockedGrade.id),
    );
    expect(onGradeUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ is_locked: true }),
    );
  });

  it("shows a generic lock error message when lockGrade fails (no PII)", async () => {
    mockLockGrade.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );
    const user = userEvent.setup();

    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    await user.click(
      screen.getByRole("button", { name: /lock this grade as final/i }),
    );

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(/failed to lock grade/i);
  });
});

// ---------------------------------------------------------------------------
// EssayReviewPanel — total score display
// ---------------------------------------------------------------------------

describe("EssayReviewPanel — total score display", () => {
  it("displays total_score / max_possible_score on initial render", () => {
    const grade = makeGrade({ total_score: "7", max_possible_score: "10" });

    render(
      <EssayReviewPanel
        grade={grade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    // The live total initially equals total_score (no local overrides yet)
    expect(
      screen.getByLabelText(/total score: 7 out of 10/i),
    ).toBeInTheDocument();
  });

  it("recalculates the live total score when a score input changes", async () => {
    const grade = makeGrade({ total_score: "7", max_possible_score: "10" });
    const user = userEvent.setup();

    render(
      <EssayReviewPanel
        grade={grade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    // Find the first score input (Thesis criterion, initial final_score=3)
    const scoreInputs = screen.getAllByRole("spinbutton");
    const firstInput = scoreInputs[0];

    // Change the score from 3 → 5; live total should update to 4+5=9
    await user.clear(firstInput);
    await user.type(firstInput, "5");

    // Live total should now be 5 + 4 = 9
    await waitFor(() =>
      expect(
        screen.getByLabelText(/total score: 9 out of 10/i),
      ).toBeInTheDocument(),
    );
  });
});

// ---------------------------------------------------------------------------
// EssayReviewPanel — criterion display
// ---------------------------------------------------------------------------

describe("EssayReviewPanel — criterion display", () => {
  it("renders criterion names from the criteria prop", () => {
    render(
      <EssayReviewPanel
        grade={makeGrade()}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.getByText(/thesis/i)).toBeInTheDocument();
    expect(screen.getByText(/evidence/i)).toBeInTheDocument();
  });

  it("renders AI score and max score for each criterion", () => {
    render(
      <EssayReviewPanel
        grade={makeGrade()}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    // First criterion: ai_score=3, max=5
    expect(screen.getAllByText(/\/\s*5/i).length).toBeGreaterThan(0);
  });

  it("renders AI justification text", () => {
    render(
      <EssayReviewPanel
        grade={makeGrade()}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    expect(
      screen.getAllByText(/synthetic ai justification/i).length,
    ).toBeGreaterThan(0);
  });

  it("shows 'Unnamed criterion' when rubric_criterion_id has no matching criterion", () => {
    const gradeWithUnmatchedCriterion = makeGrade({
      criterion_scores: [
        makeCriterionScore({
          id: "cs-zzz-999",
          rubric_criterion_id: "no-match-id",
        }),
      ],
    });

    render(
      <EssayReviewPanel
        grade={gradeWithUnmatchedCriterion}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.getByText(/unnamed criterion/i)).toBeInTheDocument();
  });

  it("maxScore fallback uses Math.max(final_score, ai_score) so an existing teacher override is not clamped", () => {
    // teacher_score=7 > ai_score=3; without the max() fallback, clamping to
    // ai_score=3 would corrupt the displayed value on the unmatched criterion.
    const gradeWithHighOverride = makeGrade({
      criterion_scores: [
        makeCriterionScore({
          id: "cs-high-override",
          rubric_criterion_id: "no-match-id", // no criterion metadata → fallback
          ai_score: 3,
          teacher_score: 7,
          final_score: 7,
        }),
      ],
    });

    render(
      <EssayReviewPanel
        grade={gradeWithHighOverride}
        criteria={CRITERIA} // no entry for "no-match-id"
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    // The displayed score input should show 7, not 3 (ai_score).
    const scoreInput = screen.getByRole("spinbutton");
    expect(scoreInput).toHaveValue(7);
  });
});

// ---------------------------------------------------------------------------
// EssayReviewPanel — summary feedback blur behaviour
// ---------------------------------------------------------------------------

describe("EssayReviewPanel — summary feedback blur behaviour", () => {
  const unlockedGrade = makeGrade({
    is_locked: false,
    summary_feedback: "AI summary feedback.",
    summary_feedback_edited: null,
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockUpdateFeedback.mockResolvedValue(unlockedGrade);
  });

  it("resets summary feedback textarea and shows error when teacher clears it", async () => {
    const user = userEvent.setup();

    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const textarea = screen.getByRole("textbox", {
      name: /overall summary feedback/i,
    });

    // Clear the textarea and blur
    await user.clear(textarea);
    fireEvent.blur(textarea);

    // Textarea should be reset to the persisted value (not stay empty)
    await waitFor(() =>
      expect(textarea).toHaveValue("AI summary feedback."),
    );

    // A validation error message should be shown
    expect(
      await screen.findByText(/summary feedback cannot be empty/i),
    ).toBeInTheDocument();

    // No API call should have been made
    expect(mockUpdateFeedback).not.toHaveBeenCalled();
  });

  it("clears the validation error and saves when a valid (non-empty) value is entered", async () => {
    const user = userEvent.setup();
    const onGradeUpdate = vi.fn();

    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={onGradeUpdate}
      />,
      { wrapper },
    );

    const textarea = screen.getByRole("textbox", {
      name: /overall summary feedback/i,
    });

    // Type a new value and blur
    await user.clear(textarea);
    await user.type(textarea, "Updated feedback.");
    fireEvent.blur(textarea);

    await waitFor(() =>
      expect(mockUpdateFeedback).toHaveBeenCalledWith(
        unlockedGrade.id,
        { summary_feedback: "Updated feedback." },
      ),
    );
  });

  it("dismisses the validation error after the teacher enters valid text following a clear attempt", async () => {
    const user = userEvent.setup();

    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const textarea = screen.getByRole("textbox", {
      name: /overall summary feedback/i,
    });

    // Step 1: clear and blur to trigger the error
    await user.clear(textarea);
    fireEvent.blur(textarea);
    expect(
      await screen.findByText(/summary feedback cannot be empty/i),
    ).toBeInTheDocument();

    // Step 2: type valid text and blur — error should be dismissed
    await user.type(textarea, "Valid feedback now.");
    fireEvent.blur(textarea);

    await waitFor(() =>
      expect(
        screen.queryByText(/summary feedback cannot be empty/i),
      ).not.toBeInTheDocument(),
    );
    expect(mockUpdateFeedback).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// EssayReviewPanel — score override save on blur
// ---------------------------------------------------------------------------

describe("EssayReviewPanel — score override save on blur", () => {
  const unlockedGrade = makeGrade({ is_locked: false });

  beforeEach(() => {
    vi.clearAllMocks();
    mockOverrideCriterionScore.mockResolvedValue(unlockedGrade);
  });

  it("calls overrideCriterionScore with correct args when score input is blurred", async () => {
    const user = userEvent.setup();

    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const scoreInputs = screen.getAllByRole("spinbutton");
    const firstInput = scoreInputs[0]; // cs-test-001

    await user.clear(firstInput);
    await user.type(firstInput, "5");
    fireEvent.blur(firstInput);

    await waitFor(() =>
      expect(mockOverrideCriterionScore).toHaveBeenCalledWith(
        unlockedGrade.id,
        "cs-test-001",
        { teacher_score: 5 },
      ),
    );
  });

  it("does NOT call overrideCriterionScore when the value is unchanged", async () => {
    const user = userEvent.setup();

    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const scoreInputs = screen.getAllByRole("spinbutton");
    const firstInput = scoreInputs[0]; // initial final_score=3

    // Clear and retype the same value
    await user.clear(firstInput);
    await user.type(firstInput, "3");
    fireEvent.blur(firstInput);

    await waitFor(() =>
      expect(mockOverrideCriterionScore).not.toHaveBeenCalled(),
    );
  });

  it("shows a generic save error message when overrideCriterionScore fails", async () => {
    mockOverrideCriterionScore.mockRejectedValue(
      new ApiError(409, { code: "GRADE_LOCKED", message: "locked" }),
    );
    const user = userEvent.setup();

    render(
      <EssayReviewPanel
        grade={unlockedGrade}
        criteria={CRITERIA}
        onGradeUpdate={vi.fn()}
      />,
      { wrapper },
    );

    const scoreInputs = screen.getAllByRole("spinbutton");
    await user.clear(scoreInputs[0]);
    await user.type(scoreInputs[0], "5");
    fireEvent.blur(scoreInputs[0]);

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent(/grade is locked and cannot be edited/i);
  });
});
