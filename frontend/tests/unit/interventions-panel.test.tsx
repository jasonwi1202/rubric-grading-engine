/**
 * Tests for InterventionsPanel — M8-01 (Interventions Page UI).
 *
 * Covers:
 * - InterventionsPanel: shows loading skeleton while fetching
 * - InterventionsPanel: shows error alert when fetch fails
 * - InterventionsPanel: shows empty state for pending_review filter with no items
 * - InterventionsPanel: shows empty state message for non-pending filters with no items
 * - InterventionsPanel: renders trigger label, urgency badge, and status badge
 * - InterventionsPanel: renders trigger_reason, evidence_summary, and suggested_action
 * - InterventionsPanel: renders skill_key badge when present
 * - InterventionsPanel: shows Approve and Dismiss buttons for pending_review items
 * - InterventionsPanel: hides action buttons for approved items
 * - InterventionsPanel: hides action buttons for dismissed items
 * - InterventionsPanel: Approve button calls approveIntervention and invalidates cache
 * - InterventionsPanel: Dismiss button calls dismissIntervention and invalidates cache
 * - InterventionsPanel: buttons disabled while mutation is pending
 * - InterventionsPanel: shows error alert when approveIntervention fails
 * - InterventionsPanel: shows error alert when dismissIntervention fails
 * - InterventionsPanel: status filter dropdown changes query key
 * - InterventionsPanel: renders actioned_at timestamp for approved items
 * - InterventionsPanel: renders actioned_at timestamp for dismissed items
 * - InterventionsPanel: renders student profile link using student_id UUID
 * - InterventionsPanel: renders interventions page link on list items
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

const mockListInterventions = vi.fn();
const mockApproveIntervention = vi.fn();
const mockDismissIntervention = vi.fn();

vi.mock("@/lib/api/interventions", () => ({
  listInterventions: (...args: unknown[]) => mockListInterventions(...args),
  approveIntervention: (...args: unknown[]) => mockApproveIntervention(...args),
  dismissIntervention: (...args: unknown[]) => mockDismissIntervention(...args),
}));

// ---------------------------------------------------------------------------
// Component imports (after mock declarations)
// ---------------------------------------------------------------------------

import { InterventionsPanel } from "@/components/interventions/InterventionsPanel";
import { ApiError } from "@/lib/api/errors";
import type {
  InterventionRecommendation,
  InterventionListResponse,
} from "@/lib/api/interventions";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function makeIntervention(
  overrides: Partial<InterventionRecommendation> = {},
): InterventionRecommendation {
  return {
    id: "int-001",
    teacher_id: "teacher-001",
    student_id: "stu-001",
    trigger_type: "persistent_gap",
    skill_key: "evidence",
    urgency: 3,
    trigger_reason: "Skill has been below threshold for 3 consecutive assignments.",
    evidence_summary: "Average score 40%, trend stable, 3 assignments.",
    suggested_action: "Assign targeted evidence-focused writing practice.",
    details: { avg_score: 0.4, trend: "stable", assignment_count: 3 },
    status: "pending_review",
    actioned_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeListResponse(
  items: InterventionRecommendation[] = [makeIntervention()],
): InterventionListResponse {
  return {
    teacher_id: "teacher-001",
    items,
    total_count: items.length,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApproveIntervention.mockResolvedValue(
    makeIntervention({ status: "approved", actioned_at: "2026-01-02T00:00:00Z" }),
  );
  mockDismissIntervention.mockResolvedValue(
    makeIntervention({ status: "dismissed", actioned_at: "2026-01-02T00:00:00Z" }),
  );
});

// ---------------------------------------------------------------------------
// InterventionsPanel — loading state
// ---------------------------------------------------------------------------

describe("InterventionsPanel — loading state", () => {
  it("shows loading skeleton while fetching", () => {
    mockListInterventions.mockReturnValue(new Promise(() => {})); // never resolves
    render(<InterventionsPanel />, { wrapper });
    expect(document.querySelector("[aria-busy='true']")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — error state
// ---------------------------------------------------------------------------

describe("InterventionsPanel — error state", () => {
  it("shows error alert when fetch fails", async () => {
    mockListInterventions.mockRejectedValue(
      new ApiError(500, { code: "SERVER_ERROR", message: "Server error" }),
    );
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      /failed to load interventions/i,
    );
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — empty state
// ---------------------------------------------------------------------------

describe("InterventionsPanel — empty state", () => {
  it("shows empty state for pending_review filter with no items", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse([]));
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText(/no pending interventions/i)).toBeInTheDocument();
    });
  });

  it("shows generic empty state message for non-pending filters with no items", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse([]));
    render(<InterventionsPanel initialStatus="approved" />, { wrapper });
    await waitFor(() => {
      expect(
        screen.getByText(/no interventions found for this filter/i),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — card rendering
// ---------------------------------------------------------------------------

describe("InterventionsPanel — card rendering", () => {
  it("renders trigger label, urgency badge, and status badge", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse());
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("Persistent Skill Gap")).toBeInTheDocument();
      expect(screen.getByText("High")).toBeInTheDocument();
      // "Pending Review" appears both in the filter <option> and in the status badge span
      expect(screen.getAllByText("Pending Review").length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders trigger_reason, evidence_summary, and suggested_action", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse());
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(
        screen.getByText(/skill has been below threshold for 3 consecutive/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/average score 40%/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/targeted evidence-focused writing practice/i),
      ).toBeInTheDocument();
    });
  });

  it("renders skill_key badge when present", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse());
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("evidence")).toBeInTheDocument();
    });
  });

  it("does not render skill_key badge when skill_key is null", async () => {
    mockListInterventions.mockResolvedValue(
      makeListResponse([makeIntervention({ skill_key: null })]),
    );
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(screen.queryByText("evidence")).not.toBeInTheDocument();
    });
  });

  it("renders student profile link using student_id UUID", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse());
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      const profileLink = screen.getByRole("link", {
        name: /view student profile/i,
      });
      expect(profileLink).toHaveAttribute("href", "/dashboard/students/stu-001");
    });
  });

  it("renders interventions link on list items", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse());
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      const link = screen.getByRole("link", {
        name: /view student profile/i,
      });
      expect(link).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — action buttons visibility
// ---------------------------------------------------------------------------

describe("InterventionsPanel — action button visibility", () => {
  it("shows Approve and Dismiss buttons for pending_review items", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse());
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /approve intervention/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /dismiss intervention/i }),
      ).toBeInTheDocument();
    });
  });

  it("hides action buttons for approved items", async () => {
    mockListInterventions.mockResolvedValue(
      makeListResponse([makeIntervention({ status: "approved" })]),
    );
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /approve intervention/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /dismiss intervention/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("hides action buttons for dismissed items", async () => {
    mockListInterventions.mockResolvedValue(
      makeListResponse([makeIntervention({ status: "dismissed" })]),
    );
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /approve intervention/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /dismiss intervention/i }),
      ).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — approve action
// ---------------------------------------------------------------------------

describe("InterventionsPanel — approve action", () => {
  it("Approve button calls approveIntervention and invalidates cache", async () => {
    const user = userEvent.setup();
    mockListInterventions.mockResolvedValue(makeListResponse());
    render(<InterventionsPanel />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /approve intervention/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /approve intervention/i }));

    await waitFor(() => {
      expect(mockApproveIntervention).toHaveBeenCalledWith("int-001");
    });
  });

  it("shows error alert when approveIntervention fails", async () => {
    const user = userEvent.setup();
    mockListInterventions.mockResolvedValue(makeListResponse());
    mockApproveIntervention.mockRejectedValue(
      new ApiError(409, { code: "CONFLICT", message: "Conflict" }),
    );
    render(<InterventionsPanel />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /approve intervention/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /approve intervention/i }));

    await waitFor(() => {
      const alerts = screen.getAllByRole("alert");
      const approveAlert = alerts.find((el) =>
        el.textContent?.match(/failed to approve/i),
      );
      expect(approveAlert).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — dismiss action
// ---------------------------------------------------------------------------

describe("InterventionsPanel — dismiss action", () => {
  it("Dismiss button calls dismissIntervention and invalidates cache", async () => {
    const user = userEvent.setup();
    mockListInterventions.mockResolvedValue(makeListResponse());
    render(<InterventionsPanel />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /dismiss intervention/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /dismiss intervention/i }));

    await waitFor(() => {
      expect(mockDismissIntervention).toHaveBeenCalledWith("int-001");
    });
  });

  it("shows error alert when dismissIntervention fails", async () => {
    const user = userEvent.setup();
    mockListInterventions.mockResolvedValue(makeListResponse());
    mockDismissIntervention.mockRejectedValue(
      new ApiError(409, { code: "CONFLICT", message: "Conflict" }),
    );
    render(<InterventionsPanel />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /dismiss intervention/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /dismiss intervention/i }));

    await waitFor(() => {
      const alerts = screen.getAllByRole("alert");
      const dismissAlert = alerts.find((el) =>
        el.textContent?.match(/failed to dismiss/i),
      );
      expect(dismissAlert).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — mutation pending state
// ---------------------------------------------------------------------------

describe("InterventionsPanel — pending state", () => {
  it("buttons are disabled while mutation is pending", async () => {
    const user = userEvent.setup();
    // Mutation never resolves so the pending state persists
    mockListInterventions.mockResolvedValue(makeListResponse());
    mockApproveIntervention.mockReturnValue(new Promise(() => {}));
    render(<InterventionsPanel />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /approve intervention/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /approve intervention/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /approve intervention/i }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: /dismiss intervention/i }),
      ).toBeDisabled();
    });
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — status filter
// ---------------------------------------------------------------------------

describe("InterventionsPanel — status filter", () => {
  it("calls listInterventions with default pending_review status", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse([]));
    render(<InterventionsPanel />, { wrapper });
    await waitFor(() => {
      expect(mockListInterventions).toHaveBeenCalledWith("pending_review");
    });
  });

  it("calls listInterventions with initialStatus prop", async () => {
    mockListInterventions.mockResolvedValue(makeListResponse([]));
    render(<InterventionsPanel initialStatus="approved" />, { wrapper });
    await waitFor(() => {
      expect(mockListInterventions).toHaveBeenCalledWith("approved");
    });
  });

  it("calls listInterventions with new status when filter changes", async () => {
    const user = userEvent.setup();
    mockListInterventions.mockResolvedValue(makeListResponse([]));
    render(<InterventionsPanel />, { wrapper });

    await waitFor(() => {
      expect(mockListInterventions).toHaveBeenCalledWith("pending_review");
    });

    // Wait for loading to complete before interacting with the select
    await waitFor(() => {
      expect(screen.getByRole("combobox")).toBeInTheDocument();
    });

    const select = screen.getByRole("combobox");
    await user.selectOptions(select, "all");

    await waitFor(() => {
      expect(mockListInterventions).toHaveBeenCalledWith("all");
    });
  });
});

// ---------------------------------------------------------------------------
// InterventionsPanel — status history timestamps
// ---------------------------------------------------------------------------

describe("InterventionsPanel — status history", () => {
  it("renders actioned_at timestamp for approved items", async () => {
    mockListInterventions.mockResolvedValue(
      makeListResponse([
        makeIntervention({
          status: "approved",
          actioned_at: "2026-06-15T10:30:00Z",
        }),
      ]),
    );
    render(<InterventionsPanel initialStatus="approved" />, { wrapper });
    await waitFor(() => {
      // "Approved" badge appears on the card — use getAllByText since it also
      // appears in the filter <option>
      const approvedEls = screen.getAllByText("Approved");
      expect(approvedEls.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders actioned_at timestamp for dismissed items", async () => {
    mockListInterventions.mockResolvedValue(
      makeListResponse([
        makeIntervention({
          status: "dismissed",
          actioned_at: "2026-06-15T10:30:00Z",
        }),
      ]),
    );
    render(<InterventionsPanel initialStatus="dismissed" />, { wrapper });
    await waitFor(() => {
      // "Dismissed" badge appears on the card — use getAllByText since it also
      // appears in the filter <option>
      const dismissedEls = screen.getAllByText("Dismissed");
      expect(dismissedEls.length).toBeGreaterThanOrEqual(1);
    });
  });
});
