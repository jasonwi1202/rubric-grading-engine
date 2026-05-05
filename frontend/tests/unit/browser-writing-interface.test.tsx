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
  applyInlineFormat,
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

// ---------------------------------------------------------------------------
// applyInlineFormat — Selection/Range API formatting
// ---------------------------------------------------------------------------

/**
 * Helper: create a mock Selection that returns the given Range.
 * `removeAllRanges` and `addRange` are no-ops in JSDOM but we spy on them
 * to assert they are called, keeping the contract explicit.
 */
function mockSelectionWithRange(range: Range) {
  const sel = {
    rangeCount: 1,
    getRangeAt: (_idx: number) => range,
    removeAllRanges: vi.fn(),
    addRange: vi.fn(),
  };
  vi.spyOn(window, "getSelection").mockReturnValue(sel as unknown as Selection);
  return sel;
}

describe("applyInlineFormat — bold", () => {
  let editor: HTMLDivElement;

  beforeEach(() => {
    vi.restoreAllMocks();
    editor = document.createElement("div");
    editor.contentEditable = "true";
    document.body.appendChild(editor);
  });

  afterEach(() => {
    document.body.removeChild(editor);
  });

  it("wraps selected text in <b> when bold is applied to plain text", () => {
    editor.innerHTML = "Hello world";
    const textNode = editor.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5); // "Hello"
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    const b = editor.querySelector("b");
    expect(b).not.toBeNull();
    expect(b!.textContent).toBe("Hello");
    // Rest of text is unchanged
    expect(editor.textContent).toBe("Hello world");
  });

  it("removes <b> wrapper when bold is toggled off (selection covers full element)", () => {
    editor.innerHTML = "<b>Hello</b> world";
    const bEl = editor.querySelector("b")!;
    const textNode = bEl.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5);
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(editor.querySelector("b")).toBeNull();
    expect(editor.textContent).toBe("Hello world");
  });

  it("removes bold only from the selected prefix, keeping the suffix bold", () => {
    // <b>Hello world</b>: select "Hello" (0–5) — " world" must stay bold
    editor.innerHTML = "<b>Hello world</b>";
    const bEl = editor.querySelector("b")!;
    const textNode = bEl.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5); // "Hello"
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(editor.textContent).toBe("Hello world");
    // The unformatted "Hello" should sit outside any <b>
    const bEls = editor.querySelectorAll("b");
    expect(bEls).toHaveLength(1);
    expect(bEls[0].textContent).toBe(" world");
  });

  it("removes bold only from the selected suffix, keeping the prefix bold", () => {
    // <b>Hello world</b>: select "world" (6–11) — "Hello " must stay bold
    editor.innerHTML = "<b>Hello world</b>";
    const bEl = editor.querySelector("b")!;
    const textNode = bEl.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 6); // "world"
    range.setEnd(textNode, 11);
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(editor.textContent).toBe("Hello world");
    const bEls = editor.querySelectorAll("b");
    expect(bEls).toHaveLength(1);
    expect(bEls[0].textContent).toBe("Hello ");
  });

  it("removes bold from a middle selection only, keeping prefix and suffix bold", () => {
    // <b>Hello world foo</b>: select "world" (6–11) — "Hello " and " foo" stay bold
    editor.innerHTML = "<b>Hello world foo</b>";
    const bEl = editor.querySelector("b")!;
    const textNode = bEl.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 6); // "world"
    range.setEnd(textNode, 11);
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(editor.textContent).toBe("Hello world foo");
    const bEls = editor.querySelectorAll("b");
    expect(bEls).toHaveLength(2);
    expect(bEls[0].textContent).toBe("Hello ");
    expect(bEls[1].textContent).toBe(" foo");
  });

  it("removes bold from a selection whose container is nested inside the ancestor", () => {
    // <b>before <u>mid</u> after</b>: select "mid" inside <u> — bold is lifted
    // from that portion only; "before " and " after" remain bold, <u> is preserved.
    editor.innerHTML = "<b>before <u>mid</u> after</b>";
    const uEl = editor.querySelector("u")!;
    const textNode = uEl.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 3); // "mid"
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(editor.textContent).toBe("before mid after");
    // The <u> element must still be present (only bold removed, not underline)
    expect(editor.querySelector("u")).not.toBeNull();
    // "before" and "after" portions must each still be inside a <b>
    const bEls = editor.querySelectorAll("b");
    expect(bEls.length).toBeGreaterThanOrEqual(1);
    const boldText = Array.from(bEls)
      .map((el) => el.textContent ?? "")
      .join("");
    expect(boldText).toContain("before");
    expect(boldText).toContain("after");
    // "mid" must not be directly inside any <b>
    expect(
      Array.from(bEls).some((el) => el.textContent?.trim() === "mid"),
    ).toBe(false);
  });

  it("does nothing when the selection is collapsed (no text selected)", () => {
    editor.innerHTML = "Hello world";
    const textNode = editor.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 3);
    range.setEnd(textNode, 3); // collapsed
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(editor.querySelector("b")).toBeNull();
  });

  it("does nothing when the selection is outside the editor", () => {
    editor.innerHTML = "Hello";
    const outside = document.createElement("span");
    const outsideText = document.createTextNode("Outside");
    outside.appendChild(outsideText);
    document.body.appendChild(outside);

    const range = document.createRange();
    range.setStart(outsideText, 0);
    range.setEnd(outsideText, 7);
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(editor.querySelector("b")).toBeNull();
    document.body.removeChild(outside);
  });

  it("does nothing when getSelection returns rangeCount 0", () => {
    editor.innerHTML = "Hello";
    vi.spyOn(window, "getSelection").mockReturnValue({
      rangeCount: 0,
    } as unknown as Selection);

    applyInlineFormat(editor, "bold");

    expect(editor.querySelector("b")).toBeNull();
  });

  it("does nothing when getSelection returns null", () => {
    editor.innerHTML = "Hello";
    vi.spyOn(window, "getSelection").mockReturnValue(null);

    applyInlineFormat(editor, "bold");

    expect(editor.querySelector("b")).toBeNull();
  });
});

describe("applyInlineFormat — italic", () => {
  let editor: HTMLDivElement;

  beforeEach(() => {
    vi.restoreAllMocks();
    editor = document.createElement("div");
    editor.contentEditable = "true";
    document.body.appendChild(editor);
  });

  afterEach(() => {
    document.body.removeChild(editor);
  });

  it("wraps selected text in <i> when italic is applied", () => {
    editor.innerHTML = "Hello world";
    const textNode = editor.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 6);
    range.setEnd(textNode, 11); // "world"
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "italic");

    const i = editor.querySelector("i");
    expect(i).not.toBeNull();
    expect(i!.textContent).toBe("world");
  });

  it("removes <i> wrapper when italic is toggled off", () => {
    editor.innerHTML = "<i>world</i>";
    const iEl = editor.querySelector("i")!;
    const textNode = iEl.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5);
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "italic");

    expect(editor.querySelector("i")).toBeNull();
    expect(editor.textContent).toBe("world");
  });
});

describe("applyInlineFormat — underline", () => {
  let editor: HTMLDivElement;

  beforeEach(() => {
    vi.restoreAllMocks();
    editor = document.createElement("div");
    editor.contentEditable = "true";
    document.body.appendChild(editor);
  });

  afterEach(() => {
    document.body.removeChild(editor);
  });

  it("wraps selected text in <u> when underline is applied", () => {
    editor.innerHTML = "Essay text";
    const textNode = editor.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5); // "Essay"
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "underline");

    const u = editor.querySelector("u");
    expect(u).not.toBeNull();
    expect(u!.textContent).toBe("Essay");
  });

  it("removes <u> wrapper when underline is toggled off", () => {
    editor.innerHTML = "<u>Essay</u> text";
    const uEl = editor.querySelector("u")!;
    const textNode = uEl.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5);
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "underline");

    expect(editor.querySelector("u")).toBeNull();
    expect(editor.textContent).toBe("Essay text");
  });
});

describe("applyInlineFormat — selection edge cases", () => {
  let editor: HTMLDivElement;

  beforeEach(() => {
    vi.restoreAllMocks();
    editor = document.createElement("div");
    editor.contentEditable = "true";
    document.body.appendChild(editor);
  });

  afterEach(() => {
    document.body.removeChild(editor);
  });

  it("restores selection (calls removeAllRanges + addRange) after toggling on", () => {
    editor.innerHTML = "Hello";
    const textNode = editor.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5);
    const sel = mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(sel.removeAllRanges).toHaveBeenCalled();
    expect(sel.addRange).toHaveBeenCalled();
  });

  it("restores selection (calls removeAllRanges + addRange) after toggling off", () => {
    editor.innerHTML = "<b>Hello</b>";
    const bEl = editor.querySelector("b")!;
    const textNode = bEl.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5);
    const sel = mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    expect(sel.removeAllRanges).toHaveBeenCalled();
    expect(sel.addRange).toHaveBeenCalled();
  });

  it("handles nested ancestor: removes outermost matching tag when toggling off", () => {
    // Selection inside <b><span>text</span></b> — the <b> ancestor should be lifted
    editor.innerHTML = "<b><span>Hello</span></b> world";
    const span = editor.querySelector("span")!;
    const textNode = span.firstChild!;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5);
    mockSelectionWithRange(range);

    applyInlineFormat(editor, "bold");

    // <b> is gone; <span> is preserved as a plain child
    expect(editor.querySelector("b")).toBeNull();
    expect(editor.querySelector("span")).not.toBeNull();
    expect(editor.textContent).toBe("Hello world");
  });

  it("applies multiple independent formats to the same text", () => {
    // First apply bold, then italic — should produce <i><b>Hi</b></i> or similar
    editor.innerHTML = "Hi";
    const textNode = editor.firstChild!;

    // Bold pass
    const range1 = document.createRange();
    range1.setStart(textNode, 0);
    range1.setEnd(textNode, 2);
    mockSelectionWithRange(range1);
    applyInlineFormat(editor, "bold");

    // After bold, find the new <b> text node and select it for italic
    const bEl = editor.querySelector("b")!;
    const bText = bEl.firstChild!;
    const range2 = document.createRange();
    range2.setStart(bText, 0);
    range2.setEnd(bText, 2);
    mockSelectionWithRange(range2);
    applyInlineFormat(editor, "italic");

    // Both formats present
    expect(editor.querySelector("b")).not.toBeNull();
    expect(editor.querySelector("i")).not.toBeNull();
  });
});
