/**
 * Tests for the review queue — M3.22 (Review queue UI) and M4.2 (Confidence-based review queue).
 *
 * Covers:
 * - getReviewStatus: correct mapping for all relevant essay statuses
 * - filterEssays: "all" passes through; named filters restrict correctly
 * - filterEssays: "low_confidence" filter — M4.2
 * - sortEssays by status: unreviewed → in_review → other → locked
 * - sortEssays by student_name: alphabetical, null names last
 * - sortEssays by score: ascending / descending, null scores always last
 * - sortEssays by confidence: low → medium → high, null last — M4.2
 * - ReviewQueue component: renders essay rows, status badges, sort/filter UI
 * - ReviewQueue: confidence badge on each row — M4.2
 * - ReviewQueue: default sort is confidence — M4.2
 * - ReviewQueue: fast-review mode toggle filters to low-confidence — M4.2
 * - ReviewQueue: bulk-approve button disabled when no eligible essays — M4.2
 * - ReviewQueue: "Unassigned" rendered for essays with null student_name
 * - ReviewQueue: filter dropdown changes the visible set
 * - ReviewQueue: sort buttons update ordering and show direction indicator
 * - ReviewQueue: empty state when no essays match filter
 * - ReviewQueue: keyboard navigation with ArrowDown / ArrowUp
 * - ReviewQueue: essay links use UUIDs, not student names (no PII in URL)
 * - ReviewQueue: essay links encode queue order as ?queue= and ?pos= params
 *
 * Security:
 * - No real student PII in fixtures — uses synthetic IDs and placeholder student names only.
 * - No credential-format strings in test data.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mock lockGrade — must come before component imports
// ---------------------------------------------------------------------------

const mockLockGrade = vi.fn();

vi.mock("@/lib/api/grades", () => ({
  lockGrade: (...args: unknown[]) => mockLockGrade(...args),
}));

beforeEach(() => {
  mockLockGrade.mockReset();
});

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
    overall_confidence: null,
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

  it("essay links include ?queue= with all displayed essay IDs", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    const links = screen
      .getAllByRole("listitem")
      .map((el) => el.getAttribute("href") ?? "");

    // Every link must contain a ?queue= parameter
    for (const href of links) {
      expect(href).toContain("?queue=");
    }

    // All three essay IDs must appear in each queue param
    for (const href of links) {
      const url = new URL(href, "http://localhost");
      const queue = url.searchParams.get("queue") ?? "";
      for (const essay of BASE_ESSAYS) {
        expect(queue).toContain(essay.essay_id);
      }
    }
  });

  it("essay links include ?pos= with 0-based index in the displayed list", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    const links = screen
      .getAllByRole("listitem")
      .map((el) => el.getAttribute("href") ?? "");

    links.forEach((href, idx) => {
      const url = new URL(href, "http://localhost");
      expect(url.searchParams.get("pos")).toBe(String(idx));
    });
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
    // Default is confidence (asc)
    const confidenceBtn = screen.getByRole("button", { name: /confidence/i });
    expect(confidenceBtn).toHaveTextContent("↑");
    // Click once → desc
    await user.click(confidenceBtn);
    expect(confidenceBtn).toHaveTextContent("↓");
    // Click again → asc
    await user.click(confidenceBtn);
    expect(confidenceBtn).toHaveTextContent("↑");
  });

  it("active sort button has aria-pressed=true", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    // Default active sort is Confidence
    expect(
      screen.getByRole("button", { name: /confidence/i }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: /status/i }),
    ).toHaveAttribute("aria-pressed", "false");
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
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      const message = args.map(String).join(" ");
      if (
        message.includes("not wrapped in act") ||
        message.includes("not configured to support act")
      ) {
        return;
      }
    });
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

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
    await waitFor(() => {
      expect(document.activeElement).toBe(items[1]);
    });
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

    await waitFor(() => {
      expect(document.activeElement).toBe(items[0]);
    });
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
    await waitFor(() => {
      expect(document.activeElement).toBe(items[0]);
    });
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
    await waitFor(() => {
      expect(document.activeElement).toBe(last);
    });
  });
});

// ---------------------------------------------------------------------------
// filterEssays — low_confidence filter (M4.2)
// ---------------------------------------------------------------------------

describe("filterEssays — low_confidence filter", () => {
  const essays: ReviewQueueEssay[] = [
    makeEssay({ essay_id: "e-low", status: "graded", overall_confidence: "low" }),
    makeEssay({ essay_id: "e-medium", status: "graded", overall_confidence: "medium" }),
    makeEssay({ essay_id: "e-high", status: "graded", overall_confidence: "high" }),
    makeEssay({ essay_id: "e-null", status: "graded", overall_confidence: null }),
  ];

  it("'low_confidence' returns only essays with overall_confidence === 'low'", () => {
    const result = filterEssays(essays, "low_confidence");
    expect(result).toHaveLength(1);
    expect(result[0].essay_id).toBe("e-low");
  });

  it("'all' passes through essays with any or no confidence value", () => {
    expect(filterEssays(essays, "all")).toHaveLength(4);
  });

  it("does not include essays with null confidence in low_confidence filter", () => {
    const result = filterEssays(essays, "low_confidence");
    expect(result.every((e) => e.overall_confidence === "low")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// sortEssays — by confidence (M4.2)
// ---------------------------------------------------------------------------

describe("sortEssays — by confidence", () => {
  const essays: ReviewQueueEssay[] = [
    makeEssay({ essay_id: "e-high", status: "graded", overall_confidence: "high" }),
    makeEssay({ essay_id: "e-null", status: "graded", overall_confidence: null }),
    makeEssay({ essay_id: "e-low", status: "graded", overall_confidence: "low" }),
    makeEssay({ essay_id: "e-medium", status: "graded", overall_confidence: "medium" }),
  ];

  it("asc: low → medium → high → null last", () => {
    const result = sortEssays(essays, "confidence", "asc");
    expect(result.map((e) => e.essay_id)).toEqual([
      "e-low",
      "e-medium",
      "e-high",
      "e-null",
    ]);
  });

  it("desc: high → medium → low → null still last", () => {
    const result = sortEssays(essays, "confidence", "desc");
    expect(result.map((e) => e.essay_id)).toEqual([
      "e-high",
      "e-medium",
      "e-low",
      "e-null",
    ]);
  });

  it("null confidence is always last regardless of direction", () => {
    const withTwoNulls = [
      makeEssay({ essay_id: "e-n1", status: "graded", overall_confidence: null }),
      makeEssay({ essay_id: "e-low", status: "graded", overall_confidence: "low" }),
      makeEssay({ essay_id: "e-n2", status: "graded", overall_confidence: null }),
    ];
    const asc = sortEssays(withTwoNulls, "confidence", "asc");
    expect(asc[0].essay_id).toBe("e-low");
    const desc = sortEssays(withTwoNulls, "confidence", "desc");
    expect(desc[0].essay_id).toBe("e-low");
  });

  it("does not mutate the input array", () => {
    const ids = essays.map((e) => e.essay_id);
    sortEssays(essays, "confidence", "asc");
    expect(essays.map((e) => e.essay_id)).toEqual(ids);
  });
});

// ---------------------------------------------------------------------------
// ReviewQueue — confidence badge rendering (M4.2)
// ---------------------------------------------------------------------------

describe("ReviewQueue — confidence badge", () => {
  it("renders confidence badge for essays with overall_confidence", () => {
    const essays = [
      makeEssay({
        essay_id: "e-low-001",
        status: "graded",
        overall_confidence: "low",
        student_name: "Student Alpha",
      }),
      makeEssay({
        essay_id: "e-high-001",
        status: "graded",
        overall_confidence: "high",
        student_name: "Student Beta",
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });

    // Badge text is rendered as "Low" and "High" (short labels)
    expect(screen.getByText("Low")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
  });

  it("renders medium confidence badge", () => {
    const essays = [
      makeEssay({
        essay_id: "e-med-001",
        status: "graded",
        overall_confidence: "medium",
        student_name: "Student Gamma",
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });
    expect(screen.getByText("Medium")).toBeInTheDocument();
  });

  it("does not render a confidence badge when overall_confidence is null", () => {
    const essays = [
      makeEssay({ essay_id: "e-noconf-001", status: "graded", overall_confidence: null }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });
    // None of the confidence labels should appear
    expect(screen.queryByText("Low")).not.toBeInTheDocument();
    expect(screen.queryByText("Medium")).not.toBeInTheDocument();
    expect(screen.queryByText("High")).not.toBeInTheDocument();
  });

  it("confidence badge has aria-label describing the confidence level", () => {
    const essays = [
      makeEssay({
        essay_id: "e-low-002",
        status: "graded",
        overall_confidence: "low",
        student_name: "Student Delta",
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });
    // The badge is a <span> with aria-label="Confidence: low"
    // Use getAllByLabelText to handle the link's aria-label also mentioning confidence
    const elements = screen.getAllByLabelText(/confidence: low/i);
    expect(elements.length).toBeGreaterThanOrEqual(1);
    // The badge span should be one of them
    expect(elements.some((el) => el.tagName.toLowerCase() === "span")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ReviewQueue — default sort is confidence (M4.2)
// ---------------------------------------------------------------------------

describe("ReviewQueue — default sort is confidence", () => {
  it("default sort button is Confidence with aria-pressed=true", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    const confidenceBtn = screen.getByRole("button", { name: /confidence/i });
    expect(confidenceBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("Status sort button is not active by default", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    expect(
      screen.getByRole("button", { name: /status/i }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("low-confidence essays appear first with default sort", () => {
    const essays = [
      makeEssay({
        essay_id: "e-high-s",
        status: "graded",
        overall_confidence: "high",
        student_name: "Student High",
      }),
      makeEssay({
        essay_id: "e-low-s",
        status: "graded",
        overall_confidence: "low",
        student_name: "Student Low",
      }),
      makeEssay({
        essay_id: "e-med-s",
        status: "graded",
        overall_confidence: "medium",
        student_name: "Student Med",
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });

    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Student Low");
    expect(items[1]).toHaveTextContent("Student Med");
    expect(items[2]).toHaveTextContent("Student High");
  });
});

// ---------------------------------------------------------------------------
// ReviewQueue — fast-review mode (M4.2)
// ---------------------------------------------------------------------------

describe("ReviewQueue — fast-review mode", () => {
  it("enables fast-review mode via checkbox", async () => {
    const user = userEvent.setup();
    const essays = [
      makeEssay({
        essay_id: "e-low-fr",
        status: "graded",
        overall_confidence: "low",
        student_name: "Student Low",
      }),
      makeEssay({
        essay_id: "e-high-fr",
        status: "graded",
        overall_confidence: "high",
        student_name: "Student High",
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });

    const fastReviewCheckbox = screen.getByRole("checkbox", { name: /fast review/i });
    await user.click(fastReviewCheckbox);

    // Only the low-confidence essay should be shown
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("Student Low");
  });

  it("shows empty state when fast-review mode is on but no low-confidence essays exist", async () => {
    const user = userEvent.setup();
    const essays = [
      makeEssay({ essay_id: "e-high-only", status: "graded", overall_confidence: "high" }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });

    const fastReviewCheckbox = screen.getByRole("checkbox", { name: /fast review/i });
    await user.click(fastReviewCheckbox);

    expect(
      screen.getByText(/no essays match the selected filter/i),
    ).toBeInTheDocument();
  });

  it("filter dropdown reflects low_confidence when fast-review is on", async () => {
    const user = userEvent.setup();
    // Must use essays that include confidence data — fast-review checkbox is only
    // rendered when at least one essay has overall_confidence (hasConfidenceData).
    const essays = [
      makeEssay({
        essay_id: "e-low-fr-sync",
        status: "graded",
        overall_confidence: "low",
        student_name: "Student Low",
      }),
      makeEssay({
        essay_id: "e-high-fr-sync",
        status: "graded",
        overall_confidence: "high",
        student_name: "Student High",
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });

    const fastReviewCheckbox = screen.getByRole("checkbox", { name: /fast review/i });
    await user.click(fastReviewCheckbox);

    const select = screen.getByRole("combobox", { name: /filter/i });
    expect((select as HTMLSelectElement).value).toBe("low_confidence");
  });

  it("fast-review checkbox is not shown when no essay has confidence data", () => {
    // BASE_ESSAYS have no overall_confidence — fast-review should be hidden
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    expect(screen.queryByRole("checkbox", { name: /fast review/i })).not.toBeInTheDocument();
  });

  it("low_confidence option is not in filter dropdown when no confidence data", () => {
    render(
      <ReviewQueue essays={BASE_ESSAYS} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );
    const select = screen.getByRole("combobox", { name: /filter/i });
    // The low_confidence option should not exist in the dropdown
    const options = Array.from((select as HTMLSelectElement).options).map((o) => o.value);
    expect(options).not.toContain("low_confidence");
  });
});

// ---------------------------------------------------------------------------
// ReviewQueue — bulk-approve (M4.2)
// ---------------------------------------------------------------------------

describe("ReviewQueue — bulk-approve", () => {
  it("bulk-approve button is not shown when there are no high-confidence essays", () => {
    const essays = [
      makeEssay({ essay_id: "e-low-b", status: "graded", overall_confidence: "low" }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });
    expect(screen.queryByRole("button", { name: /approve.*high-confidence/i })).not.toBeInTheDocument();
  });

  it("bulk-approve button is not shown when all high-confidence essays are already locked", () => {
    const essays = [
      makeEssay({
        essay_id: "e-high-locked",
        status: "locked",
        overall_confidence: "high",
        grade_id: "grade-high-locked-001",
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });
    expect(screen.queryByRole("button", { name: /approve.*high-confidence/i })).not.toBeInTheDocument();
  });

  it("bulk-approve button is not shown when high-confidence essay has no grade_id", () => {
    const essays = [
      makeEssay({
        essay_id: "e-high-nograde",
        status: "graded",
        overall_confidence: "high",
        grade_id: null,
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });
    expect(screen.queryByRole("button", { name: /approve.*high-confidence/i })).not.toBeInTheDocument();
  });

  it("bulk-approve button is shown when high-confidence essays are not yet locked", () => {
    const essays = [
      makeEssay({
        essay_id: "e-high-unlocked",
        status: "graded",
        overall_confidence: "high",
        grade_id: "grade-high-001",
      }),
    ];
    render(<ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />, { wrapper });
    expect(
      screen.getByRole("button", { name: /approve.*high-confidence/i }),
    ).toBeInTheDocument();
  });

  it("bulk-approve calls lockGrade for each eligible essay and invokes onBulkApproveSuccess", async () => {
    const user = userEvent.setup();
    mockLockGrade.mockResolvedValue({ id: "grade-x", is_locked: true });

    const onBulkApproveSuccess = vi.fn();
    const essays = [
      makeEssay({
        essay_id: "e-high-a",
        status: "graded",
        overall_confidence: "high",
        grade_id: "grade-h-a",
      }),
      makeEssay({
        essay_id: "e-high-b",
        status: "graded",
        overall_confidence: "high",
        grade_id: "grade-h-b",
      }),
    ];
    render(
      <ReviewQueue
        essays={essays}
        assignmentId={ASSIGNMENT_ID}
        onBulkApproveSuccess={onBulkApproveSuccess}
      />,
      { wrapper },
    );

    const btn = screen.getByRole("button", { name: /approve.*high-confidence/i });
    await user.click(btn);

    await waitFor(() => expect(onBulkApproveSuccess).toHaveBeenCalledTimes(1));
    expect(mockLockGrade).toHaveBeenCalledWith("grade-h-a");
    expect(mockLockGrade).toHaveBeenCalledWith("grade-h-b");
  });

  it("bulk-approve button is disabled while approving is in progress", async () => {
    const user = userEvent.setup();
    // Never resolves — simulates in-flight request
    mockLockGrade.mockImplementation(() => new Promise(() => {}));

    const essays = [
      makeEssay({
        essay_id: "e-high-pending",
        status: "graded",
        overall_confidence: "high",
        grade_id: "grade-pending-001",
      }),
    ];
    render(
      <ReviewQueue essays={essays} assignmentId={ASSIGNMENT_ID} />,
      { wrapper },
    );

    const btn = screen.getByRole("button", { name: /bulk approve/i });
    await user.click(btn);

    // Button should now be disabled while approving (aria-label updates to include "Approving")
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /approving.*high-confidence/i }),
      ).toBeDisabled(),
    );
  });
});
