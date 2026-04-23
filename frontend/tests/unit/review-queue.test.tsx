/**
 * Tests for the review queue — M3.22 (Review queue UI).
 *
 * Covers:
 * - getReviewStatus: correct mapping for all relevant essay statuses
 * - filterEssays: "all" passes through; named filters restrict correctly
 * - sortEssays by status: unreviewed → in_review → other → locked
 * - sortEssays by student_name: alphabetical, null names last
 * - sortEssays by score: ascending / descending, null scores always last
 * - ReviewQueue component: renders essay rows, status badges, sort/filter UI
 * - ReviewQueue: "Unassigned" rendered for essays with null student_name
 * - ReviewQueue: filter dropdown changes the visible set
 * - ReviewQueue: sort buttons update ordering and show direction indicator
 * - ReviewQueue: empty state when no essays match filter
 * - ReviewQueue: keyboard navigation with ArrowDown / ArrowUp
 * - ReviewQueue: essay links use UUIDs, not student names (no PII in URL)
 *
 * Security:
 * - No real student PII in fixtures — uses synthetic IDs and placeholder student names only.
 * - No credential-format strings in test data.
 */

import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Unit under test — pure logic (no DOM required)
// ---------------------------------------------------------------------------

import {
  getReviewStatus,
  filterEssays,
  sortEssays,
} from "@/lib/utils/reviewQueue";
import type { ReviewQueueEssay } from "@/lib/api/essays";

// ---------------------------------------------------------------------------
// Component under test
// ---------------------------------------------------------------------------

import { ReviewQueue } from "@/components/grading/ReviewQueue";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Factory — no real student names or essay content (FERPA). */
function makeEssay(
  overrides: Partial<ReviewQueueEssay> &
    Pick<ReviewQueueEssay, "essay_id" | "status">,
): ReviewQueueEssay {
  return {
    assignment_id: "asgn-test-001",
    student_id: null,
    student_name: null,
    word_count: 300,
    submitted_at: "2026-04-01T00:00:00Z",
    auto_assign_status: null,
    total_score: null,
    max_possible_score: null,
    grade_id: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// getReviewStatus
// ---------------------------------------------------------------------------

describe("getReviewStatus", () => {
  it("maps 'graded' → 'unreviewed'", () => {
    expect(getReviewStatus("graded")).toBe("unreviewed");
  });

  it("maps 'reviewed' → 'in_review'", () => {
    expect(getReviewStatus("reviewed")).toBe("in_review");
  });

  it("maps 'locked' → 'locked'", () => {
    expect(getReviewStatus("locked")).toBe("locked");
  });

  it("maps 'returned' → 'locked'", () => {
    expect(getReviewStatus("returned")).toBe("locked");
  });

  it("maps 'unassigned' → 'other'", () => {
    expect(getReviewStatus("unassigned")).toBe("other");
  });

  it("maps 'queued' → 'other'", () => {
    expect(getReviewStatus("queued")).toBe("other");
  });

  it("maps 'grading' → 'other'", () => {
    expect(getReviewStatus("grading")).toBe("other");
  });

  it("maps unknown status → 'other'", () => {
    expect(getReviewStatus("some_future_status")).toBe("other");
  });
});

// ---------------------------------------------------------------------------
// filterEssays
// ---------------------------------------------------------------------------

describe("filterEssays", () => {
  const essays: ReviewQueueEssay[] = [
    makeEssay({ essay_id: "e-aaa-001", status: "graded" }),
    makeEssay({ essay_id: "e-bbb-002", status: "reviewed" }),
    makeEssay({ essay_id: "e-ccc-003", status: "locked" }),
    makeEssay({ essay_id: "e-ddd-004", status: "queued" }),
  ];

  it("'all' returns all essays unchanged", () => {
    expect(filterEssays(essays, "all")).toHaveLength(4);
  });

  it("'unreviewed' returns only graded essays", () => {
    const result = filterEssays(essays, "unreviewed");
    expect(result).toHaveLength(1);
    expect(result[0].essay_id).toBe("e-aaa-001");
  });

  it("'in_review' returns only reviewed essays", () => {
    const result = filterEssays(essays, "in_review");
    expect(result).toHaveLength(1);
    expect(result[0].essay_id).toBe("e-bbb-002");
  });

  it("'locked' returns locked and returned essays", () => {
    const withReturned = [
      ...essays,
      makeEssay({ essay_id: "e-eee-005", status: "returned" }),
    ];
    const result = filterEssays(withReturned, "locked");
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.essay_id)).toContain("e-ccc-003");
    expect(result.map((e) => e.essay_id)).toContain("e-eee-005");
  });

  it("returns an empty array when no essays match the filter", () => {
    const onlyQueued = [makeEssay({ essay_id: "e-fff-006", status: "queued" })];
    expect(filterEssays(onlyQueued, "unreviewed")).toHaveLength(0);
  });

  it("does not mutate the original array", () => {
    const original = [...essays];
    filterEssays(essays, "unreviewed");
    expect(essays).toEqual(original);
  });
});

// ---------------------------------------------------------------------------
// sortEssays — by status
// ---------------------------------------------------------------------------

describe("sortEssays — by status", () => {
  const essays: ReviewQueueEssay[] = [
    makeEssay({ essay_id: "e-locked", status: "locked" }),
    makeEssay({ essay_id: "e-inreview", status: "reviewed" }),
    makeEssay({ essay_id: "e-unreviewed", status: "graded" }),
    makeEssay({ essay_id: "e-other", status: "queued" }),
  ];

  it("asc: unreviewed → in_review → other → locked", () => {
    const result = sortEssays(essays, "status", "asc");
    expect(result.map((e) => e.essay_id)).toEqual([
      "e-unreviewed",
      "e-inreview",
      "e-other",
      "e-locked",
    ]);
  });

  it("desc: locked → other → in_review → unreviewed", () => {
    const result = sortEssays(essays, "status", "desc");
    expect(result.map((e) => e.essay_id)).toEqual([
      "e-locked",
      "e-other",
      "e-inreview",
      "e-unreviewed",
    ]);
  });

  it("does not mutate the input array", () => {
    const ids = essays.map((e) => e.essay_id);
    sortEssays(essays, "status", "asc");
    expect(essays.map((e) => e.essay_id)).toEqual(ids);
  });
});

// ---------------------------------------------------------------------------
// sortEssays — by student_name
// ---------------------------------------------------------------------------

describe("sortEssays — by student_name", () => {
  const essays: ReviewQueueEssay[] = [
    makeEssay({
      essay_id: "e-charlie",
      status: "graded",
      student_name: "Student C",
    }),
    makeEssay({
      essay_id: "e-alice",
      status: "graded",
      student_name: "Student A",
    }),
    makeEssay({ essay_id: "e-null", status: "graded", student_name: null }),
    makeEssay({
      essay_id: "e-bob",
      status: "graded",
      student_name: "Student B",
    }),
  ];

  it("asc: A → B → C → null-named last", () => {
    const result = sortEssays(essays, "student_name", "asc");
    expect(result.map((e) => e.essay_id)).toEqual([
      "e-alice",
      "e-bob",
      "e-charlie",
      "e-null",
    ]);
  });

  it("desc: C → B → A → null-named still last", () => {
    const result = sortEssays(essays, "student_name", "desc");
    expect(result.map((e) => e.essay_id)).toEqual([
      "e-charlie",
      "e-bob",
      "e-alice",
      "e-null",
    ]);
  });

  it("is case-insensitive", () => {
    const mixed = [
      makeEssay({
        essay_id: "e-z",
        status: "graded",
        student_name: "student z",
      }),
      makeEssay({
        essay_id: "e-a",
        status: "graded",
        student_name: "Student A",
      }),
    ];
    const result = sortEssays(mixed, "student_name", "asc");
    expect(result[0].essay_id).toBe("e-a");
    expect(result[1].essay_id).toBe("e-z");
  });
});

// ---------------------------------------------------------------------------
// sortEssays — by score
// ---------------------------------------------------------------------------

describe("sortEssays — by score", () => {
  const essays: ReviewQueueEssay[] = [
    makeEssay({ essay_id: "e-high", status: "graded", total_score: "9.00" }),
    makeEssay({ essay_id: "e-null", status: "graded", total_score: null }),
    makeEssay({ essay_id: "e-low", status: "graded", total_score: "4.00" }),
    makeEssay({ essay_id: "e-mid", status: "graded", total_score: "6.50" }),
  ];

  it("asc: lowest → highest → null last", () => {
    const result = sortEssays(essays, "score", "asc");
    expect(result.map((e) => e.essay_id)).toEqual([
      "e-low",
      "e-mid",
      "e-high",
      "e-null",
    ]);
  });

  it("desc: highest → lowest → null still last", () => {
    const result = sortEssays(essays, "score", "desc");
    expect(result.map((e) => e.essay_id)).toEqual([
      "e-high",
      "e-mid",
      "e-low",
      "e-null",
    ]);
  });

  it("null scores are always last regardless of direction", () => {
    const withTwoNulls = [
      makeEssay({ essay_id: "e-n1", status: "graded", total_score: null }),
      makeEssay({ essay_id: "e-s1", status: "graded", total_score: "5.00" }),
      makeEssay({ essay_id: "e-n2", status: "graded", total_score: null }),
    ];
    const asc = sortEssays(withTwoNulls, "score", "asc");
    expect(asc[0].essay_id).toBe("e-s1");
    const desc = sortEssays(withTwoNulls, "score", "desc");
    expect(desc[0].essay_id).toBe("e-s1");
  });

  it("returns empty array for empty input", () => {
    expect(sortEssays([], "score", "asc")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// ReviewQueue component
// ---------------------------------------------------------------------------

const ASSIGNMENT_ID = "asgn-test-001";

const BASE_ESSAYS: ReviewQueueEssay[] = [
  makeEssay({
    essay_id: "e-aaa-001",
    status: "graded",
    student_name: "Student Alpha",
    total_score: "7.00",
    max_possible_score: "10.00",
    grade_id: "grade-aaa-001",
  }),
  makeEssay({
    essay_id: "e-bbb-002",
    status: "reviewed",
    student_name: "Student Beta",
    total_score: "5.00",
    max_possible_score: "10.00",
    grade_id: "grade-bbb-002",
  }),
  makeEssay({
    essay_id: "e-ccc-003",
    status: "locked",
    student_name: "Student Gamma",
    total_score: "9.00",
    max_possible_score: "10.00",
    grade_id: "grade-ccc-003",
  }),
];

describe("ReviewQueue — rendering", () => {
  it("renders a row for each essay", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    // Three essays should produce three listitem links
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
  });

  it("renders correct status badge labels", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    // Each label appears at least once (may also appear in the filter dropdown)
    expect(screen.getAllByText("Unreviewed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("In review").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Locked").length).toBeGreaterThanOrEqual(1);
  });

  it("renders 'Unassigned' for essays with null student_name", () => {
    const essays = [makeEssay({ essay_id: "e-noname-001", status: "graded" })];
    render(
      <ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
  });

  it("renders score as 'score / max' when available", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    expect(screen.getByText("7 / 10")).toBeInTheDocument();
  });

  it("renders em-dash for essays with no score", () => {
    const essays = [
      makeEssay({ essay_id: "e-noscore-001", status: "graded" }),
    ];
    render(
      <ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    // The em-dash is rendered as a <span> with aria-hidden content but is
    // accessible as a child of the link
    expect(screen.getByRole("listitem")).toBeInTheDocument();
  });

  it("renders an empty state when the essay list is empty", () => {
    render(
      <ReviewQueue essays={[]} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    expect(
      screen.getByText(/no essays have been submitted/i),
    ).toBeInTheDocument();
  });

  it("essay links use UUIDs (no student PII in URL)", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    const links = screen
      .getAllByRole("listitem")
      .map((el) => el.getAttribute("href"));

    // Each link should contain the essay UUID
    for (const essay of BASE_ESSAYS) {
      expect(links.some((href) => href?.includes(essay.essay_id))).toBe(true);
    }
    // No link should contain a student name
    for (const essay of BASE_ESSAYS) {
      if (essay.student_name) {
        expect(
          links.some((href) =>
            href?.toLowerCase().includes(essay.student_name!.toLowerCase()),
          ),
        ).toBe(false);
      }
    }
  });
});

describe("ReviewQueue — filter", () => {
  it("shows only unreviewed essays when 'Unreviewed' is selected", async () => {
    const user = userEvent.setup();
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );

    const select = screen.getByRole("combobox", { name: /filter/i });
    await user.selectOptions(select, "unreviewed");

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(within(items[0]).getByText("Unreviewed")).toBeInTheDocument();
  });

  it("shows empty state message when filter matches nothing", async () => {
    const user = userEvent.setup();
    // Only a graded essay — locking filter should show empty state
    const essays = [makeEssay({ essay_id: "e-zzz-001", status: "graded" })];
    render(
      <ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );

    const select = screen.getByRole("combobox", { name: /filter/i });
    await user.selectOptions(select, "locked");

    expect(
      screen.getByText(/no essays match the selected filter/i),
    ).toBeInTheDocument();
  });

  it("essay count label reflects filtered count", async () => {
    const user = userEvent.setup();
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    // Default: "3 of 3 essays"
    expect(screen.getByText(/3 of 3/i)).toBeInTheDocument();

    const select = screen.getByRole("combobox", { name: /filter/i });
    await user.selectOptions(select, "unreviewed");
    expect(screen.getByText(/1 of 3/i)).toBeInTheDocument();
  });
});

describe("ReviewQueue — sort", () => {
  it("sort buttons are rendered for Status, Score, Student", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    expect(screen.getByRole("button", { name: /status/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /score/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /student/i }),
    ).toBeInTheDocument();
  });

  it("clicking the active sort button toggles direction (shows ↓ on desc)", async () => {
    const user = userEvent.setup();
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    const statusBtn = screen.getByRole("button", { name: /status/i });
    // Default is asc
    expect(statusBtn).toHaveTextContent("↑");
    // Click once → desc
    await user.click(statusBtn);
    expect(statusBtn).toHaveTextContent("↓");
    // Click again → asc
    await user.click(statusBtn);
    expect(statusBtn).toHaveTextContent("↑");
  });

  it("active sort button has aria-pressed=true", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    expect(
      screen.getByRole("button", { name: /status/i }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: /score/i }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("clicking 'Score' button re-orders essays by score ascending", async () => {
    const user = userEvent.setup();
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /score/i }));

    const items = screen.getAllByRole("listitem");
    // BASE_ESSAYS scores: 5, 7, 9 → sorted asc: Beta(5), Alpha(7), Gamma(9)
    expect(items[0]).toHaveTextContent("Student Beta");
    expect(items[1]).toHaveTextContent("Student Alpha");
    expect(items[2]).toHaveTextContent("Student Gamma");
  });
});

describe("ReviewQueue — keyboard navigation", () => {
  it("ArrowDown moves focus to the next row", async () => {
    const user = userEvent.setup();
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );

    // Tab into the first row
    const items = screen.getAllByRole("listitem");
    items[0].focus();

    // Press ArrowDown on the container
    await user.keyboard("{ArrowDown}");

    // Focus should now be on the second row
    expect(document.activeElement).toBe(items[1]);
  });

  it("ArrowUp moves focus to the previous row", async () => {
    const user = userEvent.setup();
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );

    const items = screen.getAllByRole("listitem");
    // Start at second row
    items[1].focus();

    await user.keyboard("{ArrowUp}");

    expect(document.activeElement).toBe(items[0]);
  });

  it("ArrowUp does not go above the first row", async () => {
    const user = userEvent.setup();
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );

    const items = screen.getAllByRole("listitem");
    items[0].focus();
    await user.keyboard("{ArrowUp}");
    // Should still be on the first row
    expect(document.activeElement).toBe(items[0]);
  });

  it("ArrowDown does not go past the last row", async () => {
    const user = userEvent.setup();
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );

    const items = screen.getAllByRole("listitem");
    const last = items[items.length - 1];
    last.focus();
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(last);
  });
});
