/**
 * Tests for TextCommentBankPicker — M8-02 (Text comment bank UI).
 *
 * Covers (per acceptance criteria):
 * - Toggle button renders and opens/closes the picker panel.
 * - "Save to bank" button is disabled when currentText is empty.
 * - "Save to bank" button calls createCommentBankEntry with the current text
 *   and shows "Saved!" briefly on success.
 * - Save error message shown on createCommentBankEntry failure.
 * - Saved comments are listed when the picker is opened.
 * - Empty-state message shown when bank has no entries.
 * - Load error shown when listCommentBank fails.
 * - Search input fetches suggestions via getCommentBankSuggestions.
 * - Suggestions are displayed with a match-percentage badge.
 * - Suggest empty-state shown when no suggestions match.
 * - Suggest error shown when getCommentBankSuggestions fails.
 * - Clicking "Apply" calls onApply with the entry text and shows "Applied!".
 * - Apply is disabled when isLocked=true.
 * - Delete button calls deleteCommentBankEntry and invalidates cache.
 * - Delete error shown on deleteCommentBankEntry failure.
 * - Locked notice is shown when isLocked=true.
 * - Save to bank button is disabled when isLocked=true.
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and neutral text only.
 * - No credential-format strings in test data.
 * - Error assertions verify static UI strings, not raw server messages.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — declared before component imports so vi.mock hoisting works
// ---------------------------------------------------------------------------

const mockListCommentBank = vi.fn();
const mockCreateCommentBankEntry = vi.fn();
const mockDeleteCommentBankEntry = vi.fn();
const mockGetCommentBankSuggestions = vi.fn();

vi.mock("@/lib/api/comment-bank", () => ({
  listCommentBank: (...args: unknown[]) => mockListCommentBank(...args),
  createCommentBankEntry: (...args: unknown[]) =>
    mockCreateCommentBankEntry(...args),
  deleteCommentBankEntry: (...args: unknown[]) =>
    mockDeleteCommentBankEntry(...args),
  getCommentBankSuggestions: (...args: unknown[]) =>
    mockGetCommentBankSuggestions(...args),
}));

import { TextCommentBankPicker } from "@/components/grading/TextCommentBankPicker";
import type { CommentBankEntry, CommentBankSuggestion } from "@/lib/api/comment-bank";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEntry(overrides: Partial<CommentBankEntry> = {}): CommentBankEntry {
  return {
    id: "cb-entry-001",
    text: "Good use of evidence to support claims.",
    created_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

function makeSuggestion(
  overrides: Partial<CommentBankSuggestion> = {},
): CommentBankSuggestion {
  return {
    id: "cb-suggest-001",
    text: "Strong argument development with clear transitions.",
    score: 0.85,
    created_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const CURRENT_TEXT = "Shows strong argumentation but needs more citations.";
const noop = () => {};

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockListCommentBank.mockResolvedValue([]);
  mockGetCommentBankSuggestions.mockResolvedValue([]);
});

// ---------------------------------------------------------------------------
// Toggle button
// ---------------------------------------------------------------------------

describe("TextCommentBankPicker — toggle button", () => {
  it("renders the toggle button initially", () => {
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );
    expect(
      screen.getByRole("button", { name: /text comment bank/i }),
    ).toBeInTheDocument();
  });

  it("does not show the picker panel before the toggle is clicked", () => {
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );
    expect(
      screen.queryByRole("region", { name: /text comment bank/i }),
    ).not.toBeInTheDocument();
  });

  it("opens the picker panel after clicking the toggle", async () => {
    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    expect(
      screen.getByRole("region", { name: /text comment bank/i }),
    ).toBeInTheDocument();
  });

  it("closes the picker panel when the toggle is clicked again", async () => {
    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    expect(
      screen.getByRole("region", { name: /text comment bank/i }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /hide text comment bank/i }));
    expect(
      screen.queryByRole("region", { name: /text comment bank/i }),
    ).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Save to bank
// ---------------------------------------------------------------------------

describe("TextCommentBankPicker — save to bank", () => {
  it("calls createCommentBankEntry with the current text on save", async () => {
    const entry = makeEntry();
    mockCreateCommentBankEntry.mockResolvedValue(entry);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    await user.click(
      screen.getByRole("button", { name: /save current feedback text to comment bank/i }),
    );

    await waitFor(() => {
      expect(mockCreateCommentBankEntry).toHaveBeenCalledWith(CURRENT_TEXT);
    });
  });

  it("shows 'Saved!' briefly after a successful save", async () => {
    const entry = makeEntry();
    mockCreateCommentBankEntry.mockResolvedValue(entry);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    await user.click(
      screen.getByRole("button", { name: /save current feedback text to comment bank/i }),
    );

    await waitFor(() => {
      expect(screen.getByText("Saved!")).toBeInTheDocument();
    });
  });

  it("shows a save error alert on createCommentBankEntry failure", async () => {
    mockCreateCommentBankEntry.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    await user.click(
      screen.getByRole("button", { name: /save current feedback text to comment bank/i }),
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /failed to save comment/i,
      );
    });
  });

  it("disables the save button when currentText is empty", async () => {
    const user = userEvent.setup();
    render(
      <TextCommentBankPicker currentText="" onApply={noop} isLocked={false} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    expect(
      screen.getByRole("button", { name: /save current feedback text to comment bank/i }),
    ).toBeDisabled();
  });

  it("disables the save button when isLocked=true", async () => {
    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={true}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    expect(
      screen.getByRole("button", { name: /save current feedback text to comment bank/i }),
    ).toBeDisabled();
  });

  it("shows locked read-only notice when isLocked=true", async () => {
    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={true}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/this grade is locked/i),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Browse saved comments
// ---------------------------------------------------------------------------

describe("TextCommentBankPicker — browse saved comments", () => {
  it("calls listCommentBank when the picker is opened", async () => {
    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() => {
      expect(mockListCommentBank).toHaveBeenCalledTimes(1);
    });
  });

  it("shows empty-state message when the bank is empty", async () => {
    mockListCommentBank.mockResolvedValue([]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() => {
      expect(screen.getByText(/no saved comments yet/i)).toBeInTheDocument();
    });
  });

  it("lists saved comments when the bank has entries", async () => {
    const entry = makeEntry({ text: "Good use of evidence to support claims." });
    mockListCommentBank.mockResolvedValue([entry]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() => {
      expect(
        screen.getByText("Good use of evidence to support claims."),
      ).toBeInTheDocument();
    });
  });

  it("shows error when listCommentBank fails", async () => {
    mockListCommentBank.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /failed to load saved comments/i,
      );
    });
  });
});

// ---------------------------------------------------------------------------
// Search / suggestions
// ---------------------------------------------------------------------------

describe("TextCommentBankPicker — search and suggestions", () => {
  it("disables the search input when isLocked=true", async () => {
    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={true}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    expect(
      screen.getByRole("searchbox", { name: /search saved comments/i }),
    ).toBeDisabled();
  });

  it("calls getCommentBankSuggestions when the user types in the search box", async () => {
    mockGetCommentBankSuggestions.mockResolvedValue([]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    await user.type(screen.getByRole("searchbox", { name: /search saved comments/i }), "arg");

    await waitFor(() => {
      expect(mockGetCommentBankSuggestions).toHaveBeenCalledWith("arg");
    });
  });

  it("displays suggestions returned by getCommentBankSuggestions", async () => {
    const suggestion = makeSuggestion({
      text: "Strong argument development with clear transitions.",
      score: 0.85,
    });
    mockGetCommentBankSuggestions.mockResolvedValue([suggestion]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    await user.type(screen.getByRole("searchbox", { name: /search saved comments/i }), "arg");

    await waitFor(() => {
      expect(
        screen.getByText("Strong argument development with clear transitions."),
      ).toBeInTheDocument();
    });
  });

  it("shows match percentage for suggestions", async () => {
    const suggestion = makeSuggestion({ score: 0.85 });
    mockGetCommentBankSuggestions.mockResolvedValue([suggestion]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    await user.type(screen.getByRole("searchbox", { name: /search saved comments/i }), "arg");

    await waitFor(() => {
      expect(screen.getByText(/match: 85%/i)).toBeInTheDocument();
    });
  });

  it("shows 'No matching comments found' when suggestions are empty", async () => {
    mockGetCommentBankSuggestions.mockResolvedValue([]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    await user.type(screen.getByRole("searchbox", { name: /search saved comments/i }), "xyz");

    await waitFor(() => {
      expect(screen.getByText(/no matching comments found/i)).toBeInTheDocument();
    });
  });

  it("shows error when getCommentBankSuggestions fails", async () => {
    mockGetCommentBankSuggestions.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));
    await user.type(screen.getByRole("searchbox", { name: /search saved comments/i }), "test");

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /failed to load saved comments/i,
      );
    });
  });
});

// ---------------------------------------------------------------------------
// Apply flow
// ---------------------------------------------------------------------------

describe("TextCommentBankPicker — apply flow", () => {
  it("calls onApply with the entry text when Apply is clicked", async () => {
    const entry = makeEntry({
      id: "cb-apply-001",
      text: "Good use of evidence to support claims.",
    });
    mockListCommentBank.mockResolvedValue([entry]);
    const onApply = vi.fn();

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={onApply}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: /apply saved comment/i,
        }),
      ).toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole("button", {
        name: /apply saved comment/i,
      }),
    );

    expect(onApply).toHaveBeenCalledWith("Good use of evidence to support claims.");
  });

  it("shows 'Applied!' briefly after clicking Apply", async () => {
    const entry = makeEntry({
      id: "cb-apply-002",
      text: "Good use of evidence to support claims.",
    });
    mockListCommentBank.mockResolvedValue([entry]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() =>
      screen.getByRole("button", {
        name: /apply saved comment/i,
      }),
    );

    await user.click(
      screen.getByRole("button", {
        name: /apply saved comment/i,
      }),
    );

    expect(screen.getByText("Applied!")).toBeInTheDocument();
  });

  it("disables the Apply button when isLocked=true", async () => {
    const entry = makeEntry();
    mockListCommentBank.mockResolvedValue([entry]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={true}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() =>
      screen.getByRole("button", { name: /apply saved comment/i }),
    );

    expect(
      screen.getByRole("button", { name: /apply saved comment/i }),
    ).toBeDisabled();
  });

  it("does not call onApply when isLocked=true", async () => {
    const entry = makeEntry({ id: "cb-locked-001" });
    mockListCommentBank.mockResolvedValue([entry]);
    const onApply = vi.fn();

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={onApply}
        isLocked={true}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() =>
      screen.getByRole("button", { name: /apply saved comment/i }),
    );

    // Attempt click — button is disabled so userEvent won't trigger the handler.
    await user.click(
      screen.getByRole("button", { name: /apply saved comment/i }),
    );

    expect(onApply).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Delete flow
// ---------------------------------------------------------------------------

describe("TextCommentBankPicker — delete flow", () => {
  it("calls deleteCommentBankEntry with the correct id when Delete is clicked", async () => {
    const entry = makeEntry({ id: "cb-del-001" });
    mockListCommentBank.mockResolvedValue([entry]);
    mockDeleteCommentBankEntry.mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() =>
      screen.getByRole("button", { name: /delete saved comment/i }),
    );

    await user.click(screen.getByRole("button", { name: /delete saved comment/i }));

    await waitFor(() => {
      expect(mockDeleteCommentBankEntry).toHaveBeenCalledWith("cb-del-001");
    });
  });

  it("disables the delete button when isLocked=true", async () => {
    const entry = makeEntry({ id: "cb-del-lock-001" });
    mockListCommentBank.mockResolvedValue([entry]);

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={true}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() =>
      screen.getByRole("button", { name: /delete saved comment/i }),
    );

    expect(
      screen.getByRole("button", { name: /delete saved comment/i }),
    ).toBeDisabled();
  });

  it("shows delete error alert when deleteCommentBankEntry fails", async () => {
    const entry = makeEntry({ id: "cb-del-err-001" });
    mockListCommentBank.mockResolvedValue([entry]);
    mockDeleteCommentBankEntry.mockRejectedValue(
      new ApiError(500, { code: "INTERNAL_ERROR", message: "internal" }),
    );

    const user = userEvent.setup();
    render(
      <TextCommentBankPicker
        currentText={CURRENT_TEXT}
        onApply={noop}
        isLocked={false}
      />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /text comment bank/i }));

    await waitFor(() =>
      screen.getByRole("button", { name: /delete saved comment/i }),
    );

    await user.click(screen.getByRole("button", { name: /delete saved comment/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /failed to delete comment/i,
      );
    });
  });
});
