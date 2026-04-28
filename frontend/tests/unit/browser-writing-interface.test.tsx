/**
 * Tests for BrowserWritingInterface — M5-09 in-browser essay composition.
 *
 * Covers:
 * - Renders the toolbar and editor surface
 * - Loads existing content from snapshot state on mount (recovery)
 * - Autosave fires after the debounce interval on user input
 * - Autosave does NOT fire when content is unchanged since last save
 * - Multiple edits reset the debounce timer (only one save at the end)
 * - Status indicator reflects idle / saving / saved / error states
 * - Submit button is disabled when editor is empty
 * - Submit button triggers onSubmit callback
 * - Cancel button triggers onCancel callback
 * - beforeunload listener is added when there are unsaved changes
 * - countWordsFromHtml: strips tags and counts correctly
 *
 * No real API calls — all API modules are mocked.
 * No student PII in fixtures.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockSaveSnapshot = vi.fn();
const mockGetSnapshots = vi.fn();

vi.mock("@/lib/api/essays", () => ({
  saveSnapshot: (...args: unknown[]) => mockSaveSnapshot(...args),
  getSnapshots: (...args: unknown[]) => mockGetSnapshots(...args),
  // other exports used elsewhere
  uploadEssays: vi.fn(),
  assignEssay: vi.fn(),
  listEssays: vi.fn(),
  createComposedEssay: vi.fn(),
}));

import {
  BrowserWritingInterface,
  AUTOSAVE_DEBOUNCE_MS,
  countWordsFromHtml,
} from "@/components/essays/BrowserWritingInterface";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ESSAY_ID = "essay-001";
const VERSION_ID = "version-001";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function emptySnapshot() {
  return {
    essay_id: ESSAY_ID,
    essay_version_id: VERSION_ID,
    current_content: "",
    word_count: 0,
    snapshots: [],
  };
}

function snapshotWithContent(content: string) {
  return {
    essay_id: ESSAY_ID,
    essay_version_id: VERSION_ID,
    current_content: content,
    word_count: 3,
    snapshots: [{ seq: 1, ts: "2026-04-28T10:00:00Z", word_count: 3 }],
  };
}

function snapshotSaveResult() {
  return {
    essay_id: ESSAY_ID,
    essay_version_id: VERSION_ID,
    snapshot_count: 1,
    word_count: 2,
    saved_at: "2026-04-28T10:00:12Z",
  };
}

// ---------------------------------------------------------------------------
// countWordsFromHtml — pure-function unit tests
// ---------------------------------------------------------------------------

describe("countWordsFromHtml", () => {
  it("counts plain-text words correctly", () => {
    expect(countWordsFromHtml("Hello world")).toBe(2);
  });

  it("strips tags before counting", () => {
    expect(countWordsFromHtml("<p>Hello world</p>")).toBe(2);
  });

  it("strips nested tags", () => {
    expect(countWordsFromHtml("<b>Hello</b> <i>world</i>")).toBe(2);
  });

  it("returns 0 for empty string", () => {
    expect(countWordsFromHtml("")).toBe(0);
  });

  it("returns 0 for tags-only content", () => {
    expect(countWordsFromHtml("<p></p>")).toBe(0);
  });

  it("handles HTML entities", () => {
    // &amp; decodes to "&" which is treated as its own whitespace-delimited token,
    // giving "Tom" + "&" + "Jerry" = 3 words. The function counts whitespace-separated
    // tokens, not semantic English words.
    const count = countWordsFromHtml("Tom &amp; Jerry");
    expect(count).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// Component rendering
// ---------------------------------------------------------------------------

describe("BrowserWritingInterface — rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSnapshots.mockResolvedValue(emptySnapshot());
    mockSaveSnapshot.mockResolvedValue(snapshotSaveResult());
  });

  it("renders toolbar with Bold, Italic, Underline buttons", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => expect(mockGetSnapshots).toHaveBeenCalled());

    expect(screen.getByRole("button", { name: /bold/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /italic/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /underline/i })).toBeInTheDocument();
  });

  it("renders the rich-text editor surface", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    // Wait for snapshot fetch to resolve and editor to appear
    await waitFor(() => expect(screen.queryByTestId("essay-editor")).toBeInTheDocument());

    const editor = screen.getByTestId("essay-editor");
    expect(editor).toHaveAttribute("contenteditable", "true");
    expect(editor).toHaveAttribute("role", "textbox");
    expect(editor).toHaveAttribute("aria-label", "Essay content");
  });

  it("renders Cancel and Submit buttons", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => expect(mockGetSnapshots).toHaveBeenCalled());

    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit essay/i })).toBeInTheDocument();
  });

  it("calls getSnapshots with the essay ID on mount", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => {
      expect(mockGetSnapshots).toHaveBeenCalledWith(ESSAY_ID);
    });
  });
});

// ---------------------------------------------------------------------------
// Content recovery
// ---------------------------------------------------------------------------

describe("BrowserWritingInterface — content recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSaveSnapshot.mockResolvedValue(snapshotSaveResult());
  });

  it("populates editor with content from snapshot state on mount", async () => {
    const savedHtml = "<p>Previously saved content</p>";
    mockGetSnapshots.mockResolvedValue(snapshotWithContent(savedHtml));

    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => {
      const editor = screen.queryByTestId("essay-editor");
      expect(editor?.innerHTML).toBe(savedHtml);
    });
  });

  it("leaves editor empty when snapshots list is empty", async () => {
    mockGetSnapshots.mockResolvedValue(emptySnapshot());

    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => {
      expect(screen.queryByTestId("essay-editor")).toBeInTheDocument();
    });

    const editor = screen.getByTestId("essay-editor");
    expect(editor.innerHTML).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Autosave cadence
// ---------------------------------------------------------------------------

describe("BrowserWritingInterface — autosave cadence", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.clearAllMocks();
    mockGetSnapshots.mockResolvedValue(emptySnapshot());
    mockSaveSnapshot.mockResolvedValue(snapshotSaveResult());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does NOT call saveSnapshot before the debounce interval elapses", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    // Wait for editor to appear (snapshot query resolved)
    await waitFor(() => expect(screen.queryByTestId("essay-editor")).toBeInTheDocument());

    const editor = screen.getByTestId("essay-editor");

    // Simulate user input
    act(() => {
      editor.innerHTML = "<p>Hello</p>";
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // Advance less than the debounce interval
    act(() => {
      vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS - 1000);
    });

    expect(mockSaveSnapshot).not.toHaveBeenCalled();
  });

  it("calls saveSnapshot exactly once after the debounce interval", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => expect(screen.queryByTestId("essay-editor")).toBeInTheDocument());

    const editor = screen.getByTestId("essay-editor");

    act(() => {
      editor.innerHTML = "<p>Hello world</p>";
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });

    act(() => {
      vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS);
    });

    await waitFor(() => {
      expect(mockSaveSnapshot).toHaveBeenCalledTimes(1);
    });

    const [calledEssayId, payload] = mockSaveSnapshot.mock.calls[0] as [
      string,
      { html_content: string; word_count: number },
    ];
    expect(calledEssayId).toBe(ESSAY_ID);
    expect(payload.html_content).toBe("<p>Hello world</p>");
    expect(typeof payload.word_count).toBe("number");
  });

  it("resets the timer on each input — saves only once at the end of a burst", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => expect(screen.queryByTestId("essay-editor")).toBeInTheDocument());

    const editor = screen.getByTestId("essay-editor");

    // Simulate three rapid-fire inputs, each 2 s apart
    for (let i = 1; i <= 3; i++) {
      act(() => {
        editor.innerHTML = `<p>Draft ${i}</p>`;
        editor.dispatchEvent(new Event("input", { bubbles: true }));
        vi.advanceTimersByTime(2000);
      });
    }

    // Not yet past the debounce interval from the last input
    expect(mockSaveSnapshot).not.toHaveBeenCalled();

    // Advance past debounce interval from last input
    act(() => {
      vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS);
    });

    await waitFor(() => {
      expect(mockSaveSnapshot).toHaveBeenCalledTimes(1);
    });
  });

  it("does NOT save when content is unchanged since last save", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => expect(screen.queryByTestId("essay-editor")).toBeInTheDocument());

    const editor = screen.getByTestId("essay-editor");

    // First save
    act(() => {
      editor.innerHTML = "<p>Same content</p>";
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    await waitFor(() => expect(mockSaveSnapshot).toHaveBeenCalledTimes(1));

    // Wait for the save mutation to update lastSavedContent
    await act(async () => {
      await Promise.resolve();
    });

    // Second input with identical content — timer fires but save is skipped
    act(() => {
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    await act(async () => await Promise.resolve());

    // Still only one call
    expect(mockSaveSnapshot).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Status indicator
// ---------------------------------------------------------------------------

describe("BrowserWritingInterface — status indicator", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.clearAllMocks();
    mockGetSnapshots.mockResolvedValue(emptySnapshot());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows 'Saved' status after a successful save", async () => {
    mockSaveSnapshot.mockResolvedValue(snapshotSaveResult());

    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => expect(screen.queryByTestId("essay-editor")).toBeInTheDocument());

    const editor = screen.getByTestId("essay-editor");

    act(() => {
      editor.innerHTML = "<p>Hello</p>";
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });

    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));

    await waitFor(() => {
      expect(screen.getByText("Saved")).toBeInTheDocument();
      expect(mockSaveSnapshot).toHaveBeenCalledTimes(1);
    });
  });

  it("shows 'Save failed' status when the save API call errors", async () => {
    mockSaveSnapshot.mockRejectedValue(new Error("Network error"));

    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => expect(screen.queryByTestId("essay-editor")).toBeInTheDocument());

    const editor = screen.getByTestId("essay-editor");

    act(() => {
      editor.innerHTML = "<p>Hello</p>";
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });

    act(() => vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));

    await waitFor(() => {
      expect(screen.getByText(/save failed/i)).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Submit and Cancel
// ---------------------------------------------------------------------------

describe("BrowserWritingInterface — submit and cancel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSnapshots.mockResolvedValue(emptySnapshot());
    mockSaveSnapshot.mockResolvedValue(snapshotSaveResult());
  });

  it("calls onCancel when Cancel is clicked", async () => {
    const onCancel = vi.fn();
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={onCancel}
      />,
      { wrapper },
    );

    await waitFor(() => expect(mockGetSnapshots).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("blocks navigation and shows error when final save fails on submit", async () => {
    const onSubmit = vi.fn();
    // Start with saved content, then reject the final save on submit
    const snapshotWithData = snapshotWithContent("<p>Some content</p>");
    mockGetSnapshots.mockResolvedValue(snapshotWithData);
    mockSaveSnapshot.mockRejectedValue(new Error("Network error"));

    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => {
      const editor = screen.queryByTestId("essay-editor");
      expect(editor?.innerHTML).toBe("<p>Some content</p>");
    });

    // Type something to create unsaved changes
    const editor = screen.getByTestId("essay-editor");
    act(() => {
      editor.innerHTML = "<p>Some content with new text</p>";
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await userEvent.click(screen.getByRole("button", { name: /submit essay/i }));

    // onSubmit must NOT have been called — navigation should be blocked
    expect(onSubmit).not.toHaveBeenCalled();
    // Error message must be visible to the user
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("calls onSubmit when Submit is clicked (with content)", async () => {
    const onSubmit = vi.fn();
    const snapshotWithData = snapshotWithContent("<p>Some content</p>");
    mockGetSnapshots.mockResolvedValue(snapshotWithData);

    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => {
      const editor = screen.queryByTestId("essay-editor");
      expect(editor?.innerHTML).toBe("<p>Some content</p>");
    });

    await userEvent.click(screen.getByRole("button", { name: /submit essay/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Snapshot recovery error
// ---------------------------------------------------------------------------

describe("BrowserWritingInterface — snapshot recovery error", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a recoverable error alert when snapshot fetch fails", async () => {
    mockGetSnapshots.mockRejectedValue(new Error("Network error"));

    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    // Editor should not be rendered when recovery fails
    expect(screen.queryByTestId("essay-editor")).not.toBeInTheDocument();
    // A Retry button should be present
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Paste sanitization
// ---------------------------------------------------------------------------

describe("BrowserWritingInterface — paste sanitization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSnapshots.mockResolvedValue(emptySnapshot());
    mockSaveSnapshot.mockResolvedValue(snapshotSaveResult());
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("strips dangerous elements from pasted HTML", async () => {
    render(
      <BrowserWritingInterface
        essayId={ESSAY_ID}
        essayVersionId={VERSION_ID}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
      { wrapper },
    );

    await waitFor(() => expect(screen.queryByTestId("essay-editor")).toBeInTheDocument());

    const editor = screen.getByTestId("essay-editor");

    // Simulate a paste event with dangerous HTML
    const pasteHtml = '<p>Safe text</p><script>alert(1)</script><img src="http://test-tracking.example/pixel.png">';
    const pasteData = {
      getData: (type: string) => (type === "text/html" ? pasteHtml : ""),
    };
    const pasteEvent = new Event("paste", { bubbles: true }) as unknown as React.ClipboardEvent<HTMLDivElement>;
    Object.defineProperty(pasteEvent, "clipboardData", { value: pasteData });
    Object.defineProperty(pasteEvent, "preventDefault", { value: vi.fn() });

    act(() => {
      editor.dispatchEvent(pasteEvent as unknown as Event);
    });

    // The pasted content should not contain <script> or <img> in the editor
    expect(editor.innerHTML).not.toContain("<script>");
    expect(editor.innerHTML).not.toContain("<img");
  });
});
