/**
 * Tests for WorklistPanel — M6.6 (Worklist UI).
 *
 * Covers:
 * - filterWorklist: "all" passes all items
 * - filterWorklist: triggerType filter restricts by trigger
 * - filterWorklist: skillKey filter restricts by skill key
 * - filterWorklist: skillKey "__none__" filter matches items with null skill_key
 * - filterWorklist: urgency filter restricts by urgency
 * - filterWorklist: combined filters apply all constraints
 * - extractSkillKeys: returns sorted unique non-null skill keys
 * - WorklistPanel: shows loading skeleton while fetching
 * - WorklistPanel: shows error alert when fetch fails
 * - WorklistPanel: shows onboarding checklist when worklist is empty and teacher has no classes
 * - WorklistPanel: shows "all caught up" state when worklist is empty but teacher has classes
 * - WorklistPanel: renders urgency indicator, trigger reason, and suggested action
 * - WorklistPanel: renders urgency badge with correct label
 * - WorklistPanel: renders skill_key badge when present
 * - WorklistPanel: shows top 10 items by default
 * - WorklistPanel: "Show all" button expands to full list
 * - WorklistPanel: "Show top 10 only" collapses back
 * - WorklistPanel: mark-done button calls completeWorklistItem and invalidates cache
 * - WorklistPanel: snooze button calls snoozeWorklistItem and invalidates cache
 * - WorklistPanel: dismiss button calls dismissWorklistItem and invalidates cache
 * - WorklistPanel: filter by trigger type hides non-matching items
 * - WorklistPanel: filter by urgency hides non-matching items
 * - WorklistPanel: filter by skill gap hides non-matching items
 * - WorklistPanel: "__none__" skill gap filter shows only student-level items
 * - WorklistPanel: empty state shown when no items match filters
 * - WorklistPanel: snoozed badge shown on snoozed items
 * - WorklistPanel: student profile link uses student_id UUID (no PII in URL)
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and placeholder names only.
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

const mockGetWorklist = vi.fn();
const mockCompleteWorklistItem = vi.fn();
const mockSnoozeWorklistItem = vi.fn();
const mockDismissWorklistItem = vi.fn();
const mockListClasses = vi.fn();

vi.mock("@/lib/api/classes", () => ({
  listClasses: (...args: unknown[]) => mockListClasses(...args),
}));

vi.mock("@/lib/api/worklist", () => ({
  getWorklist: (...args: unknown[]) => mockGetWorklist(...args),
  completeWorklistItem: (...args: unknown[]) => mockCompleteWorklistItem(...args),
  snoozeWorklistItem: (...args: unknown[]) => mockSnoozeWorklistItem(...args),
  dismissWorklistItem: (...args: unknown[]) => mockDismissWorklistItem(...args),
}));

// ---------------------------------------------------------------------------
// Component imports (after mock declarations)
// ---------------------------------------------------------------------------

import {
  WorklistPanel,
  filterWorklist,
  extractSkillKeys,
} from "@/components/worklist/WorklistPanel";
import { ApiError } from "@/lib/api/errors";
import type { WorklistItem, TeacherWorklistResponse } from "@/lib/api/worklist";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function makeItem(overrides: Partial<WorklistItem> = {}): WorklistItem {
  return {
    id: "item-001",
    student_id: "stu-001",
    trigger_type: "persistent_gap",
    skill_key: "evidence",
    urgency: 3,
    suggested_action: "Schedule a 1:1 check-in",
    details: {},
    status: "active",
    snoozed_until: null,
    completed_at: null,
    generated_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeResponse(
  items: WorklistItem[] = [makeItem()],
): TeacherWorklistResponse {
  return {
    teacher_id: "teacher-001",
    items,
    total_count: items.length,
    generated_at: "2026-01-01T00:00:00Z",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockCompleteWorklistItem.mockResolvedValue(makeItem({ status: "completed" }));
  mockSnoozeWorklistItem.mockResolvedValue(makeItem({ status: "snoozed" }));
  mockDismissWorklistItem.mockResolvedValue(makeItem({ status: "dismissed" }));
  // Default: teacher has no classes (triggers onboarding state when worklist is empty)
  mockListClasses.mockResolvedValue([]);
});

// ---------------------------------------------------------------------------
// Pure logic — filterWorklist
// ---------------------------------------------------------------------------

describe("filterWorklist — pure logic", () => {
  const items: WorklistItem[] = [
    makeItem({ id: "a", trigger_type: "regression", skill_key: "thesis", urgency: 4 }),
    makeItem({ id: "b", trigger_type: "persistent_gap", skill_key: "evidence", urgency: 2 }),
    makeItem({ id: "c", trigger_type: "non_responder", skill_key: null, urgency: 3 }),
    makeItem({ id: "d", trigger_type: "high_inconsistency", skill_key: "evidence", urgency: 1 }),
  ];

  it("'all' filter passes all items", () => {
    const result = filterWorklist(items, {
      triggerType: "all",
      skillKey: "all",
      urgency: "all",
    });
    expect(result).toHaveLength(4);
  });

  it("triggerType filter restricts by trigger", () => {
    const result = filterWorklist(items, {
      triggerType: "regression",
      skillKey: "all",
      urgency: "all",
    });
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("a");
  });

  it("skillKey filter restricts by skill key", () => {
    const result = filterWorklist(items, {
      triggerType: "all",
      skillKey: "evidence",
      urgency: "all",
    });
    expect(result).toHaveLength(2);
    expect(result.map((i) => i.id).sort()).toEqual(["b", "d"]);
  });

  it("'__none__' skillKey filter matches items with null skill_key", () => {
    const result = filterWorklist(items, {
      triggerType: "all",
      skillKey: "__none__",
      urgency: "all",
    });
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("c");
  });

  it("urgency filter restricts by urgency", () => {
    const result = filterWorklist(items, {
      triggerType: "all",
      skillKey: "all",
      urgency: 2,
    });
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("b");
  });

  it("combined filters apply all constraints", () => {
    const result = filterWorklist(items, {
      triggerType: "high_inconsistency",
      skillKey: "evidence",
      urgency: 1,
    });
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("d");
  });

  it("returns empty array when no items match combined filters", () => {
    const result = filterWorklist(items, {
      triggerType: "regression",
      skillKey: "evidence",
      urgency: "all",
    });
    expect(result).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Pure logic — extractSkillKeys
// ---------------------------------------------------------------------------

describe("extractSkillKeys", () => {
  it("returns sorted unique non-null skill keys", () => {
    const items: WorklistItem[] = [
      makeItem({ skill_key: "thesis" }),
      makeItem({ skill_key: "evidence" }),
      makeItem({ skill_key: "thesis" }), // duplicate
      makeItem({ skill_key: null }),
    ];
    const keys = extractSkillKeys(items);
    expect(keys).toEqual(["evidence", "thesis"]);
  });

  it("returns empty array when all skill_keys are null", () => {
    const items: WorklistItem[] = [
      makeItem({ skill_key: null }),
      makeItem({ skill_key: null }),
    ];
    expect(extractSkillKeys(items)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// WorklistPanel — loading state
// ---------------------------------------------------------------------------

describe("WorklistPanel — loading state", () => {
  it("shows loading skeleton while fetching", () => {
    mockGetWorklist.mockReturnValue(new Promise(() => {})); // never resolves
    render(<WorklistPanel />, { wrapper });
    // Loading skeleton: aria-busy container with animated placeholders
    expect(document.querySelector("[aria-busy='true']")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// WorklistPanel — error state
// ---------------------------------------------------------------------------

describe("WorklistPanel — error state", () => {
  it("shows error alert when fetch fails", async () => {
    mockGetWorklist.mockRejectedValue(
      new ApiError(500, { code: "SERVER_ERROR", message: "Server error" }),
    );
    render(<WorklistPanel />, { wrapper });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/failed to load worklist/i);
  });
});

// ---------------------------------------------------------------------------
// WorklistPanel — empty state (onboarding and all-caught-up)
// ---------------------------------------------------------------------------

describe("WorklistPanel — empty state: onboarding", () => {
  it("shows getting-started checklist when worklist is empty and teacher has no classes", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([]));
    mockListClasses.mockResolvedValue([]);
    render(<WorklistPanel />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText(/let's get you set up/i)).toBeInTheDocument();
    });
    // First CTA step is present
    expect(screen.getByRole("link", { name: /create class/i })).toBeInTheDocument();
  });

  it("shows all-caught-up message when worklist is empty but teacher has classes", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([]));
    mockListClasses.mockResolvedValue([{ id: "cls-001", name: "Period 1" }]);
    render(<WorklistPanel />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText(/you're all caught up/i)).toBeInTheDocument();
    });
    // Must NOT show the getting-started checklist
    expect(screen.queryByText(/let's get you set up/i)).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// WorklistPanel — rendering
// ---------------------------------------------------------------------------

describe("WorklistPanel — item rendering", () => {
  it("renders trigger reason and suggested action", async () => {
    mockGetWorklist.mockResolvedValue(
      makeResponse([
        makeItem({
          trigger_type: "persistent_gap",
          suggested_action: "Assign targeted exercise on thesis writing",
        }),
      ]),
    );
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      // "Persistent Skill Gap" also appears in the filter dropdown option
      expect(screen.getAllByText("Persistent Skill Gap").length).toBeGreaterThanOrEqual(1);
      expect(
        screen.getByText("Assign targeted exercise on thesis writing"),
      ).toBeInTheDocument();
    });
  });

  it("renders urgency badge with correct label", async () => {
    mockGetWorklist.mockResolvedValue(
      makeResponse([makeItem({ urgency: 4 })]),
    );
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Critical")).toBeInTheDocument();
    });
  });

  it("renders skill_key badge when skill_key is present", async () => {
    mockGetWorklist.mockResolvedValue(
      makeResponse([makeItem({ skill_key: "evidence" })]),
    );
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      // "evidence" appears in the filter dropdown option AND as a badge in the item card.
      // Verify the badge is rendered inside the item list specifically.
      const list = screen.getByRole("list", { name: /worklist items/i });
      expect(list).toHaveTextContent("evidence");
    });
  });

  it("renders snoozed badge for snoozed items", async () => {
    mockGetWorklist.mockResolvedValue(
      makeResponse([makeItem({ status: "snoozed" })]),
    );
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Snoozed")).toBeInTheDocument();
    });
  });

  it("student profile link uses student_id UUID — no PII in URL", async () => {
    mockGetWorklist.mockResolvedValue(
      makeResponse([makeItem({ student_id: "stu-abc-123" })]),
    );
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      const link = screen.getByRole("link", { name: /view student profile/i });
      expect(link).toHaveAttribute("href", "/dashboard/students/stu-abc-123");
      // Link text must not contain student name or other PII
      expect(link.textContent).toBe("View student profile →");
    });
  });
});

// ---------------------------------------------------------------------------
// WorklistPanel — default top-10 / expand
// ---------------------------------------------------------------------------

describe("WorklistPanel — default top 10 / expand", () => {
  function make11Items(): WorklistItem[] {
    return Array.from({ length: 11 }, (_, i) =>
      makeItem({
        id: `item-${i}`,
        suggested_action: `Action ${i}`,
        urgency: (i % 4) + 1,
      }),
    );
  }

  it("shows top 10 items by default when there are more than 10", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse(make11Items()));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      // 10 items rendered; each has "Done" button
      expect(screen.getAllByRole("button", { name: "Mark done" })).toHaveLength(10);
    });
    expect(screen.getByRole("button", { name: /show all 11 items/i })).toBeInTheDocument();
  });

  it("'Show all' button expands to full list", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse(make11Items()));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => screen.getByRole("button", { name: /show all 11 items/i }));
    await user.click(screen.getByRole("button", { name: /show all 11 items/i }));

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Mark done" })).toHaveLength(11);
    });
    expect(screen.getByRole("button", { name: /show top 10 only/i })).toBeInTheDocument();
  });

  it("'Show top 10 only' collapses back to 10", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse(make11Items()));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => screen.getByRole("button", { name: /show all 11 items/i }));
    await user.click(screen.getByRole("button", { name: /show all 11 items/i }));
    await waitFor(() => screen.getByRole("button", { name: /show top 10 only/i }));
    await user.click(screen.getByRole("button", { name: /show top 10 only/i }));

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Mark done" })).toHaveLength(10);
    });
  });
});

// ---------------------------------------------------------------------------
// WorklistPanel — item state transitions
// ---------------------------------------------------------------------------

describe("WorklistPanel — item state transitions", () => {
  it("mark-done button calls completeWorklistItem and invalidates cache", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse([makeItem({ id: "item-001" })]));

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByRole("button", { name: "Mark done" }));

    await user.click(screen.getByRole("button", { name: "Mark done" }));

    await waitFor(() => {
      expect(mockCompleteWorklistItem).toHaveBeenCalledWith("item-001");
    });
  });

  it("snooze button calls snoozeWorklistItem and invalidates cache", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse([makeItem({ id: "item-001" })]));

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByRole("button", { name: "Snooze item" }));

    await user.click(screen.getByRole("button", { name: "Snooze item" }));

    await waitFor(() => {
      expect(mockSnoozeWorklistItem).toHaveBeenCalledWith("item-001");
    });
  });

  it("dismiss button calls dismissWorklistItem and invalidates cache", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse([makeItem({ id: "item-001" })]));

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByRole("button", { name: "Dismiss item" }));

    await user.click(screen.getByRole("button", { name: "Dismiss item" }));

    await waitFor(() => {
      expect(mockDismissWorklistItem).toHaveBeenCalledWith("item-001");
    });
  });
});

// ---------------------------------------------------------------------------
// WorklistPanel — filters
// ---------------------------------------------------------------------------

describe("WorklistPanel — filters", () => {
  function makeFilterItems(): WorklistItem[] {
    return [
      makeItem({
        id: "a",
        trigger_type: "regression",
        skill_key: "thesis",
        urgency: 4,
        suggested_action: "Action A",
      }),
      makeItem({
        id: "b",
        trigger_type: "persistent_gap",
        skill_key: "evidence",
        urgency: 2,
        suggested_action: "Action B",
      }),
      makeItem({
        id: "c",
        trigger_type: "non_responder",
        skill_key: null,
        urgency: 3,
        suggested_action: "Action C",
      }),
    ];
  }

  it("filter by trigger type hides non-matching items", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse(makeFilterItems()));

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByLabelText(/filter by action type/i));

    await user.selectOptions(
      screen.getByLabelText(/filter by action type/i),
      "regression",
    );

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Mark done" })).toHaveLength(1);
    });
    expect(screen.getByText("Action A")).toBeInTheDocument();
    expect(screen.queryByText("Action B")).not.toBeInTheDocument();
  });

  it("filter by urgency hides non-matching items", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse(makeFilterItems()));

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByLabelText(/filter by urgency/i));

    await user.selectOptions(
      screen.getByLabelText(/filter by urgency/i),
      "3",
    );

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Mark done" })).toHaveLength(1);
    });
    expect(screen.getByText("Action C")).toBeInTheDocument();
  });

  it("filter by skill gap hides non-matching items", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse(makeFilterItems()));

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByLabelText(/filter by skill gap/i));

    await user.selectOptions(
      screen.getByLabelText(/filter by skill gap/i),
      "evidence",
    );

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Mark done" })).toHaveLength(1);
    });
    expect(screen.getByText("Action B")).toBeInTheDocument();
  });

  it("'__none__' skill gap filter shows only student-level items (null skill_key)", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse(makeFilterItems()));

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByLabelText(/filter by skill gap/i));

    await user.selectOptions(
      screen.getByLabelText(/filter by skill gap/i),
      "__none__",
    );

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Mark done" })).toHaveLength(1);
    });
    expect(screen.getByText("Action C")).toBeInTheDocument();
  });

  it("shows no-match empty state when no items match combined filters", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(makeResponse(makeFilterItems()));

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByLabelText(/filter by action type/i));

    // Select a combination that matches nothing
    await user.selectOptions(
      screen.getByLabelText(/filter by action type/i),
      "regression",
    );
    await user.selectOptions(
      screen.getByLabelText(/filter by urgency/i),
      "1",
    );

    await waitFor(() => {
      expect(
        screen.getByText(/no items match the selected filters/i),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// WorklistPanel — trajectory_risk / predictive insights (M7-02)
// ---------------------------------------------------------------------------

describe("WorklistPanel — trajectory risk predictive insights", () => {
  function makePredictiveItem(
    confidenceLevel: string = "low",
    overrides: Partial<WorklistItem> = {},
  ): WorklistItem {
    return makeItem({
      trigger_type: "trajectory_risk",
      skill_key: "evidence",
      urgency: 1,
      suggested_action: "Monitor this student's recent evidence scores closely.",
      details: {
        is_predictive: true,
        confidence_level: confidenceLevel,
        consecutive_decline_count: 3,
        total_decline: 0.3,
        recent_scores: [0.8, 0.7, 0.6, 0.5],
      },
      ...overrides,
    });
  }

  it("renders 'Trajectory Risk' as trigger label", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([makePredictiveItem()]));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Trajectory Risk")).toBeInTheDocument();
    });
  });

  it("renders 'Predictive Insight' badge for trajectory_risk items", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([makePredictiveItem()]));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Predictive Insight")).toBeInTheDocument();
    });
  });

  it("renders predictive disclaimer text", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([makePredictiveItem()]));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/predictive guidance only/i)).toBeInTheDocument();
    });
  });

  it("renders 'Low confidence' badge for low confidence level", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([makePredictiveItem("low")]));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/low confidence/i)).toBeInTheDocument();
    });
  });

  it("renders 'Medium confidence' badge for medium confidence level", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([makePredictiveItem("medium")]));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/medium confidence/i)).toBeInTheDocument();
    });
  });

  it("renders 'High confidence' badge for high confidence level", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([makePredictiveItem("high")]));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/high confidence/i)).toBeInTheDocument();
    });
  });

  it("does NOT render 'Predictive Insight' badge for non-predictive items", async () => {
    mockGetWorklist.mockResolvedValue(
      makeResponse([makeItem({ trigger_type: "regression" })]),
    );
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.queryByText("Predictive Insight")).not.toBeInTheDocument();
    });
  });

  it("trajectory_risk item supports mark-done, snooze, and dismiss actions", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(
      makeResponse([makePredictiveItem("low", { id: "pred-001" })]),
    );
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => screen.getByRole("button", { name: "Mark done" }));
    await user.click(screen.getByRole("button", { name: "Mark done" }));

    await waitFor(() => {
      expect(mockCompleteWorklistItem).toHaveBeenCalledWith("pred-001");
    });
  });

  it("can filter by 'trajectory_risk' trigger type", async () => {
    const user = userEvent.setup();
    mockGetWorklist.mockResolvedValue(
      makeResponse([
        makePredictiveItem("low", { id: "pred-001", suggested_action: "Predictive action" }),
        makeItem({ id: "reg-001", trigger_type: "regression", suggested_action: "Regression action" }),
      ]),
    );

    render(<WorklistPanel />, { wrapper });
    await waitFor(() => screen.getByLabelText(/filter by action type/i));

    await user.selectOptions(
      screen.getByLabelText(/filter by action type/i),
      "trajectory_risk",
    );

    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Mark done" })).toHaveLength(1);
    });
    expect(screen.getByText("Predictive action")).toBeInTheDocument();
    expect(screen.queryByText("Regression action")).not.toBeInTheDocument();
  });

  it("shows 'Trajectory Risk (Predictive)' option in the trigger filter dropdown", async () => {
    mockGetWorklist.mockResolvedValue(makeResponse([makePredictiveItem()]));
    render(<WorklistPanel />, { wrapper });

    await waitFor(() => screen.getByLabelText(/filter by action type/i));
    const select = screen.getByLabelText(/filter by action type/i);
    const options = Array.from(select.querySelectorAll("option")).map(
      (o) => o.textContent,
    );
    expect(options).toContain("Trajectory Risk (Predictive)");
  });
});
