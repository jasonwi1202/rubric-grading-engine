/**
 * Tests for ResubmissionPanel — M6-12 (Resubmission UI).
 *
 * Covers:
 * - ResubmissionPanelEmpty: renders "No revision yet" placeholder
 * - ResubmissionPanelSkeleton: renders loading state with aria-busy
 * - ResubmissionPanel: renders version history strip with two version buttons
 * - ResubmissionPanel: version buttons are toggleable (aria-pressed)
 * - ResubmissionPanel: shows positive total score delta as "+N"
 * - ResubmissionPanel: shows negative total score delta as "−N"
 * - ResubmissionPanel: shows zero total score delta as "0"
 * - ResubmissionPanel: renders criterion delta rows with base → revised scores
 * - ResubmissionPanel: falls back to criterion_id when name not in criteria map
 * - ResubmissionPanel: shows low-effort warning banner when is_low_effort=true
 * - ResubmissionPanel: hides low-effort banner when is_low_effort=false
 * - ResubmissionPanel: shows feedback-addressed indicator (green = addressed)
 * - ResubmissionPanel: shows feedback-not-addressed indicator (red = not addressed)
 * - ResubmissionPanel: feedback detail expanded on click, collapsed on second click
 * - ResubmissionPanel: hides feedback-addressed section when feedback_addressed=null
 * - ResubmissionPanel: no-criterion-data empty state rendered when deltas is empty
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and placeholder text only.
 * - No credential-format strings in test data.
 * - Error messages are static strings; raw server text is never asserted.
 */

import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// No API calls are made in ResubmissionPanel; it is purely presentational.
// No mocks needed for API modules.

import {
  ResubmissionPanel,
  ResubmissionPanelEmpty,
  ResubmissionPanelSkeleton,
} from "@/components/grading/ResubmissionPanel";
import type { ResubmissionPanelProps } from "@/components/grading/ResubmissionPanel";
import type { RevisionComparisonResponse, FeedbackAddressedItemResponse } from "@/lib/api/resubmission";
import type { RubricSnapshotCriterion } from "@/lib/rubric/parseRubricSnapshot";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** Factory for a criterion delta — no real student data. */
function makeDelta(
  criterionId: string,
  base: number,
  revised: number,
): RevisionComparisonResponse["criterion_deltas"][number] {
  return {
    criterion_id: criterionId,
    base_score: base,
    revised_score: revised,
    delta: revised - base,
  };
}

/** Factory for a feedback-addressed item — no real student data. */
function makeFeedbackItem(
  criterionId: string,
  addressed: boolean,
  feedbackGiven = "Work on topic sentence clarity.",
  detail = "The revision showed improved topic sentences.",
): FeedbackAddressedItemResponse {
  return {
    criterion_id: criterionId,
    feedback_given: feedbackGiven,
    addressed,
    detail,
  };
}

/** Factory for a RevisionComparisonResponse — no real student data. */
function makeComparison(
  overrides: Partial<RevisionComparisonResponse> = {},
): RevisionComparisonResponse {
  return {
    id: "cmp-001",
    essay_id: "essay-001",
    base_version_id: "ver-001",
    revised_version_id: "ver-002",
    base_grade_id: "grade-001",
    revised_grade_id: "grade-002",
    total_score_delta: 2,
    criterion_deltas: [
      makeDelta("crit-001", 3, 4),
      makeDelta("crit-002", 2, 3),
    ],
    is_low_effort: false,
    low_effort_reasons: [],
    feedback_addressed: [
      makeFeedbackItem("crit-001", true),
      makeFeedbackItem("crit-002", false),
    ],
    created_at: "2026-04-30T10:00:00Z",
    ...overrides,
  };
}

/** Factory for rubric criteria — no real student data. */
function makeCriteria(): RubricSnapshotCriterion[] {
  return [
    {
      id: "crit-001",
      name: "Thesis",
      description: "Clarity of thesis statement",
      weight: 1,
      min_score: 0,
      max_score: 5,
    },
    {
      id: "crit-002",
      name: "Evidence",
      description: "Use of supporting evidence",
      weight: 1,
      min_score: 0,
      max_score: 5,
    },
  ];
}

/** Default props for ResubmissionPanel. */
function makeProps(
  overrides: Partial<ResubmissionPanelProps> = {},
): ResubmissionPanelProps {
  return {
    comparison: makeComparison(),
    criteria: makeCriteria(),
    baseVersionSubmittedAt: "2026-04-01T09:00:00Z",
    revisedVersionSubmittedAt: "2026-04-15T14:30:00Z",
    baseVersionWordCount: 450,
    revisedVersionWordCount: 520,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ResubmissionPanelEmpty", () => {
  it("renders 'No revision yet' placeholder", () => {
    render(<ResubmissionPanelEmpty />);
    expect(screen.getByText(/No revision yet/i)).toBeInTheDocument();
  });
});

describe("ResubmissionPanelSkeleton", () => {
  it("renders loading state with aria-busy=true", () => {
    render(<ResubmissionPanelSkeleton />);
    const busy = document.querySelector('[aria-busy="true"]');
    expect(busy).not.toBeNull();
    expect(busy).toHaveAttribute("aria-live", "polite");
  });
});

describe("ResubmissionPanel — version history strip", () => {
  it("renders two version buttons", () => {
    render(<ResubmissionPanel {...makeProps()} />);
    const buttons = screen.getAllByRole("button");
    const versionButtons = buttons.filter(
      (btn) =>
        btn.getAttribute("aria-pressed") !== null,
    );
    expect(versionButtons).toHaveLength(2);
  });

  it("'Version 2 (Revised)' is active by default (aria-pressed='true')", () => {
    render(<ResubmissionPanel {...makeProps()} />);
    const revisedBtn = screen.getByRole("button", {
      name: /Version 2/i,
    });
    expect(revisedBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("clicking 'Version 1' sets it as active and highlights 'Original submission' column", async () => {
    render(<ResubmissionPanel {...makeProps()} />);
    const originalBtn = screen.getByRole("button", { name: /Version 1/i });
    await userEvent.click(originalBtn);
    expect(originalBtn).toHaveAttribute("aria-pressed", "true");
    const revisedBtn = screen.getByRole("button", { name: /Version 2/i });
    expect(revisedBtn).toHaveAttribute("aria-pressed", "false");
    // The "Original submission" column heading should now be highlighted (blue text)
    const originalHeading = screen.getByText(/Original submission/i);
    expect(originalHeading).toHaveClass("text-blue-700");
    const revisedHeading = screen.getByText(/Revised submission/i);
    expect(revisedHeading).not.toHaveClass("text-blue-700");
  });

  it("shows version word counts", () => {
    render(
      <ResubmissionPanel
        {...makeProps({
          baseVersionWordCount: 450,
          revisedVersionWordCount: 520,
        })}
      />,
    );
    expect(screen.getByText(/450 words/i)).toBeInTheDocument();
    expect(screen.getByText(/520 words/i)).toBeInTheDocument();
  });
});

describe("ResubmissionPanel — score delta display", () => {
  it("shows positive total score delta as '+N'", () => {
    render(
      <ResubmissionPanel {...makeProps({ comparison: makeComparison({ total_score_delta: 3 }) })} />,
    );
    expect(screen.getByText("+3")).toBeInTheDocument();
  });

  it("shows negative total score delta as '−N' (minus sign)", () => {
    render(
      <ResubmissionPanel
        {...makeProps({ comparison: makeComparison({ total_score_delta: -2 }) })}
      />,
    );
    // The component uses the Unicode minus sign (−) not a hyphen (-)
    expect(screen.getByText("−2")).toBeInTheDocument();
  });

  it("shows zero total score delta as '0'", () => {
    render(
      <ResubmissionPanel
        {...makeProps({ comparison: makeComparison({ total_score_delta: 0 }) })}
      />,
    );
    // The total score delta badge is labelled with aria-label containing the delta value
    const deltaBadge = screen.getByLabelText(/Total score delta: 0/i);
    expect(deltaBadge).toBeInTheDocument();
    expect(deltaBadge).toHaveTextContent("0");
  });

  it("renders criterion delta rows with base → revised scores", () => {
    render(<ResubmissionPanel {...makeProps()} />);
    // Criterion "Thesis": 3 → 4
    const criterionList = screen.getByRole("list", { name: /Criterion score changes/i });
    const thesisText = within(criterionList).getByText(/Thesis/i);
    const thesisItem = thesisText.closest("li");
    if (!thesisItem) throw new Error("Thesis list item not found in DOM");
    expect(within(thesisItem).getByText("3")).toBeInTheDocument();
    expect(within(thesisItem).getByText("4")).toBeInTheDocument();
  });

  it("shows criterion delta values in criterion delta rows", () => {
    render(<ResubmissionPanel {...makeProps()} />);
    // Each criterion delta row has an aria-label "Score delta: ..."
    // Both Thesis (3→4) and Evidence (2→3) have delta=+1 in the default fixture
    const allDeltaBadges = screen.getAllByLabelText(/Score delta: \+1/i);
    expect(allDeltaBadges).toHaveLength(2);
    allDeltaBadges.forEach((badge) => {
      expect(badge).toHaveTextContent("+1");
    });
  });

  it("falls back to criterion_id when criterion not in criteria map", () => {
    const comparison = makeComparison({
      criterion_deltas: [makeDelta("unknown-crit-id", 1, 2)],
      feedback_addressed: null,
    });
    render(<ResubmissionPanel {...makeProps({ comparison, criteria: [] })} />);
    expect(screen.getByText("unknown-crit-id")).toBeInTheDocument();
  });

  it("shows empty state when criterion_deltas is empty", () => {
    const comparison = makeComparison({
      criterion_deltas: [],
      feedback_addressed: null,
    });
    render(<ResubmissionPanel {...makeProps({ comparison })} />);
    expect(screen.getByText(/No criteria data available/i)).toBeInTheDocument();
  });
});

describe("ResubmissionPanel — low-effort warning", () => {
  it("shows low-effort banner when is_low_effort=true", () => {
    const comparison = makeComparison({
      is_low_effort: true,
      low_effort_reasons: ["Word count changed by only 2 words."],
    });
    render(<ResubmissionPanel {...makeProps({ comparison })} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Low-effort revision detected/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Word count changed by only 2 words/i),
    ).toBeInTheDocument();
  });

  it("hides low-effort banner when is_low_effort=false", () => {
    const comparison = makeComparison({ is_low_effort: false });
    render(<ResubmissionPanel {...makeProps({ comparison })} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("ResubmissionPanel — feedback-addressed indicators", () => {
  it("shows 'Feedback addressed' indicator for addressed criterion (crit-001)", () => {
    render(<ResubmissionPanel {...makeProps()} />);
    // crit-001 (Thesis) has addressed=true — the button is present within the Thesis li
    const criterionList = screen.getByRole("list", { name: /Criterion score changes/i });
    const thesisText = within(criterionList).getByText(/Thesis/i);
    const thesisItem = thesisText.closest("li");
    if (!thesisItem) throw new Error("Thesis list item not found in DOM");
    expect(
      within(thesisItem).getByRole("button", { name: /Feedback addressed/i }),
    ).toBeInTheDocument();
  });

  it("shows 'Feedback not addressed' indicator for unaddressed criterion (crit-002)", () => {
    render(<ResubmissionPanel {...makeProps()} />);
    // crit-002 (Evidence) has addressed=false
    const criterionList = screen.getByRole("list", { name: /Criterion score changes/i });
    const evidenceText = within(criterionList).getByText(/Evidence/i);
    const evidenceItem = evidenceText.closest("li");
    if (!evidenceItem) throw new Error("Evidence list item not found in DOM");
    expect(
      within(evidenceItem).getByRole("button", { name: /Feedback not addressed/i }),
    ).toBeInTheDocument();
  });

  it("expands feedback detail when indicator button is clicked", async () => {
    render(<ResubmissionPanel {...makeProps()} />);
    // Find the first feedback indicator button (for "Thesis" criterion)
    const indicator = screen.getAllByRole("button", {
      name: /Feedback addressed/i,
    })[0];
    expect(indicator).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(indicator);
    expect(indicator).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Feedback given/i)).toBeInTheDocument();
    expect(screen.getByText(/Work on topic sentence clarity/i)).toBeInTheDocument();
    expect(screen.getByText(/The revision showed improved topic sentences/i)).toBeInTheDocument();
  });

  it("collapses feedback detail on second click", async () => {
    render(<ResubmissionPanel {...makeProps()} />);
    const indicator = screen.getAllByRole("button", {
      name: /Feedback addressed/i,
    })[0];
    await userEvent.click(indicator);
    await userEvent.click(indicator);
    expect(indicator).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Feedback given/i)).not.toBeInTheDocument();
  });

  it("hides feedback-addressed section when feedback_addressed is null", () => {
    const comparison = makeComparison({ feedback_addressed: null });
    render(<ResubmissionPanel {...makeProps({ comparison })} />);
    expect(
      screen.queryByText(/Feedback addressed/i),
    ).not.toBeInTheDocument();
    // The AI legend note should also be hidden
    expect(
      screen.queryByText(/generated by AI/i),
    ).not.toBeInTheDocument();
  });
});

describe("ResubmissionPanel — diff placeholder", () => {
  it("renders original and revised submission labels", () => {
    render(<ResubmissionPanel {...makeProps()} />);
    expect(screen.getByText(/Original submission/i)).toBeInTheDocument();
    expect(screen.getByText(/Revised submission/i)).toBeInTheDocument();
  });
});
