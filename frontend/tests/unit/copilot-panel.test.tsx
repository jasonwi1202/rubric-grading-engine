/**
 * Tests for CopilotPanel — M7-04 (Teacher Copilot UI).
 *
 * Covers:
 * - CopilotPanel: renders welcome message and example prompts when empty
 * - CopilotPanel: example prompt button populates query input
 * - CopilotPanel: renders class scope selector when classes are available
 * - CopilotPanel: does not render class scope selector when no classes
 * - CopilotPanel: shows loading skeleton while classes fetch
 * - CopilotPanel: shows "Thinking…" indicator while query is pending
 * - CopilotPanel: submit button is disabled while query is pending
 * - CopilotPanel: displays ranked_list response with evidence items
 * - CopilotPanel: displays summary response
 * - CopilotPanel: displays suggested next steps
 * - CopilotPanel: displays uncertainty note when has_sufficient_data is false
 * - CopilotPanel: ranked item renders student profile link with UUID
 * - CopilotPanel: ranked item without student_id shows no profile link
 * - CopilotPanel: clears input after successful response
 * - CopilotPanel: shows error alert on mutation failure
 * - CopilotPanel: shows 403 error message on forbidden response
 * - CopilotPanel: shows 503 error message on service unavailable
 * - CopilotPanel: clears conversation history when "Clear conversation" is clicked
 * - CopilotPanel: validation — empty submission shows error
 * - CopilotPanel: read-only notice is visible
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and placeholder text only.
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

const mockQueryCopilot = vi.fn();
const mockListClasses = vi.fn();

vi.mock("@/lib/api/copilot", () => ({
  queryCopilot: (...args: unknown[]) => mockQueryCopilot(...args),
}));

vi.mock("@/lib/api/classes", () => ({
  listClasses: (...args: unknown[]) => mockListClasses(...args),
}));

// ---------------------------------------------------------------------------
// Component imports (after mock declarations)
// ---------------------------------------------------------------------------

import { CopilotPanel } from "@/components/copilot/CopilotPanel";
import { ApiError } from "@/lib/api/errors";
import type { CopilotQueryResponse } from "@/lib/api/copilot";
import type { ClassResponse } from "@/lib/api/classes";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function makeResponse(
  overrides: Partial<CopilotQueryResponse> = {},
): CopilotQueryResponse {
  return {
    query_interpretation: "Identifying students who need support.",
    has_sufficient_data: true,
    uncertainty_note: null,
    response_type: "ranked_list",
    ranked_items: [
      {
        student_id: "student-uuid-001",
        student_display_name: "Student A",
        skill_dimension: "thesis",
        label: "Needs thesis support",
        value: 0.35,
        explanation: "Consistently low scores on thesis development across 3 assignments.",
      },
    ],
    summary: "Two students are struggling with thesis development.",
    suggested_next_steps: ["Schedule a 1:1 session.", "Assign a thesis workshop."],
    prompt_version: "copilot-v1",
    ...overrides,
  };
}

function makeClass(overrides: Partial<ClassResponse> = {}): ClassResponse {
  return {
    id: "class-uuid-001",
    teacher_id: "teacher-uuid-001",
    name: "Period 3 English",
    subject: "English",
    grade_level: "Grade 8",
    academic_year: "2025-2026",
    is_archived: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  // Default: no classes (so scope selector is hidden)
  mockListClasses.mockResolvedValue([]);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CopilotPanel", () => {
  it("renders welcome message and example prompts when conversation is empty", async () => {
    render(<CopilotPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText(/Ask me anything about your class data/i)).toBeInTheDocument();
    });

    // Example prompts should be shown
    expect(
      screen.getByText("Who is falling behind on thesis development?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("What should I teach tomorrow based on this week's essays?"),
    ).toBeInTheDocument();
  });

  it("shows read-only notice", async () => {
    render(<CopilotPanel />, { wrapper });
    await waitFor(() => {
      expect(
        screen.getByText(/never changes grades or triggers actions/i),
      ).toBeInTheDocument();
    });
  });

  it("example prompt button populates the query textarea", async () => {
    const user = userEvent.setup();
    render(<CopilotPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Who is falling behind on thesis development?")).toBeInTheDocument();
    });

    await user.click(
      screen.getByText("Who is falling behind on thesis development?"),
    );

    const textarea = screen.getByRole("textbox", { name: /your question/i });
    expect(textarea).toHaveValue("Who is falling behind on thesis development?");
  });

  it("renders class scope selector when classes are available", async () => {
    mockListClasses.mockResolvedValue([makeClass()]);
    render(<CopilotPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText(/scope/i)).toBeInTheDocument();
    });
    expect(screen.getByText("Period 3 English")).toBeInTheDocument();
  });

  it("does not render class scope selector when no classes exist", async () => {
    mockListClasses.mockResolvedValue([]);
    render(<CopilotPanel />, { wrapper });

    await waitFor(() => {
      expect(screen.queryByLabelText(/scope/i)).not.toBeInTheDocument();
    });
  });

  it("shows 'Thinking…' indicator while query is pending", async () => {
    const user = userEvent.setup();
    // Never resolves during this test
    mockQueryCopilot.mockImplementation(
      () => new Promise(() => {}),
    );

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    const textarea = screen.getByRole("textbox", { name: /your question/i });
    await user.type(textarea, "Who needs help?");

    const submitBtn = screen.getByRole("button", { name: /ask/i });
    await user.click(submitBtn);

    // "Thinking…" status element appears in the conversation area
    await waitFor(() => {
      expect(screen.getByRole("status")).toBeInTheDocument();
    });
  });

  it("submit button is disabled while query is pending", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockImplementation(() => new Promise(() => {}));

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    const textarea = screen.getByRole("textbox", { name: /your question/i });
    await user.type(textarea, "Who needs help?");

    const submitBtn = screen.getByRole("button", { name: /ask/i });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(submitBtn).toBeDisabled();
    });
  });

  it("displays ranked_list response with evidence items after successful query", async () => {
    const user = userEvent.setup();
    const response = makeResponse();
    mockQueryCopilot.mockResolvedValue(response);

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    const textarea = screen.getByRole("textbox", { name: /your question/i });
    await user.type(textarea, "Who needs help?");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByText("Needs thesis support")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Consistently low scores on thesis development/i),
    ).toBeInTheDocument();
    // Value badge: 35%
    expect(screen.getByText("35%")).toBeInTheDocument();
    // Skill dimension badge
    expect(screen.getByText("thesis")).toBeInTheDocument();
  });

  it("displays summary text in response", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(makeResponse());

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Summary test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(
        screen.getByText("Two students are struggling with thesis development."),
      ).toBeInTheDocument();
    });
  });

  it("displays suggested next steps", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(makeResponse());

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Next steps test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByText("Schedule a 1:1 session.")).toBeInTheDocument();
      expect(screen.getByText("Assign a thesis workshop.")).toBeInTheDocument();
    });
  });

  it("displays uncertainty note when has_sufficient_data is false", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(
      makeResponse({
        has_sufficient_data: false,
        uncertainty_note: "Fewer than 2 students have graded assignments.",
        response_type: "insufficient_data",
        ranked_items: [],
      }),
    );

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Data test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/Fewer than 2 students have graded assignments/i),
      ).toBeInTheDocument();
    });
  });

  it("ranked item renders a student profile link using UUID (no PII in URL)", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(makeResponse());

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Profile link test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      const link = screen.getByRole("link", { name: /view student profile/i });
      expect(link).toHaveAttribute("href", "/dashboard/students/student-uuid-001");
    });
  });

  it("ranked item without student_id shows no profile link", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(
      makeResponse({
        ranked_items: [
          {
            student_id: null,
            student_display_name: null,
            skill_dimension: "evidence",
            label: "Evidence skill gap",
            value: 0.42,
            explanation: "Many students show weak evidence use.",
          },
        ],
      }),
    );

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Skill gap test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByText("Evidence skill gap")).toBeInTheDocument();
    });
    expect(screen.queryByRole("link", { name: /view student profile/i })).not.toBeInTheDocument();
  });

  it("clears the query input after a successful response", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(makeResponse());

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    const textarea = screen.getByRole("textbox", { name: /your question/i });
    await user.type(textarea, "Clear after submit test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(textarea).toHaveValue("");
    });
  });

  it("shows generic error alert on mutation failure", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockRejectedValue(new Error("Network error"));

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Error test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "An error occurred. Please try again.",
      );
    });
  });

  it("shows 403 error message on forbidden response", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockRejectedValue(
      new ApiError(403, { code: "FORBIDDEN", message: "Forbidden" }),
    );

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Forbidden test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "You do not have access to this class.",
      );
    });
  });

  it("shows 503 error message on service unavailable", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockRejectedValue(
      new ApiError(503, { code: "SERVICE_UNAVAILABLE", message: "Service unavailable" }),
    );

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Service down test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "The AI service is temporarily unavailable. Please try again shortly.",
      );
    });
  });

  it("clears conversation history when 'Clear conversation' is clicked", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(makeResponse());

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Clear history test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    // Wait for response to appear in history
    await waitFor(() => {
      expect(screen.getByText("Needs thesis support")).toBeInTheDocument();
    });

    // Clear conversation
    const clearBtn = screen.getByRole("button", { name: /clear conversation/i });
    await user.click(clearBtn);

    // History should be gone, welcome message should be back
    await waitFor(() => {
      expect(screen.queryByText("Needs thesis support")).not.toBeInTheDocument();
      expect(
        screen.getByText(/Ask me anything about your class data/i),
      ).toBeInTheDocument();
    });
  });

  it("shows validation error when form is submitted empty", async () => {
    const user = userEvent.setup();
    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("button", { name: /ask/i }));

    // Submit without typing anything
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Please enter a question.");
    });
    expect(mockQueryCopilot).not.toHaveBeenCalled();
  });

  it("displays query interpretation from the response", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(makeResponse());

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Interpretation test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(
        screen.getByText("Identifying students who need support."),
      ).toBeInTheDocument();
    });
  });

  it("displays prompt version in response footer", async () => {
    const user = userEvent.setup();
    mockQueryCopilot.mockResolvedValue(makeResponse());

    render(<CopilotPanel />, { wrapper });
    await waitFor(() => screen.getByRole("textbox", { name: /your question/i }));

    await user.type(screen.getByRole("textbox", { name: /your question/i }), "Version test");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByText(/copilot-v1/i)).toBeInTheDocument();
      expect(screen.getByText(/Read-only/i)).toBeInTheDocument();
    });
  });
});
