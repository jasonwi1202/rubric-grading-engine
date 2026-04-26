/**
 * Tests for AudioRecorder — M4.10 (Audio comment recording and storage).
 *
 * Covers (per acceptance criteria):
 * - Record / Stop toggle starts and stops MediaRecorder.
 * - Max 3-minute limit is reflected in the countdown.
 * - Save calls uploadMediaComment (upload) then invalidates query cache.
 * - Delete calls deleteMediaComment then invalidates query cache.
 * - Playback URL is fetched on clicking Play (getMediaCommentUrl).
 * - Permission error degrades gracefully with a static UI message.
 * - Controls disabled when isLocked=true.
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs only.
 * - No credential-format strings in test data.
 * - Error assertions verify static UI strings, not raw server messages.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — declared before component imports so vi.mock hoisting works
// ---------------------------------------------------------------------------

const mockUpload = vi.fn();
const mockListComments = vi.fn();
const mockDelete = vi.fn();
const mockGetUrl = vi.fn();
const mockSaveToBank = vi.fn();

vi.mock("@/lib/api/media-comments", () => ({
  uploadMediaComment: (...args: unknown[]) => mockUpload(...args),
  listGradeMediaComments: (...args: unknown[]) => mockListComments(...args),
  deleteMediaComment: (...args: unknown[]) => mockDelete(...args),
  getMediaCommentUrl: (...args: unknown[]) => mockGetUrl(...args),
  saveToBank: (...args: unknown[]) => mockSaveToBank(...args),
  listBankedComments: () => Promise.resolve([]),
  applyBankedComment: () => Promise.resolve({}),
}));

import { AudioRecorder } from "@/components/grading/AudioRecorder";
import type { MediaCommentResponse } from "@/lib/api/media-comments";

// ---------------------------------------------------------------------------
// MediaRecorder mock
// ---------------------------------------------------------------------------

class MockMediaRecorder {
  state: "inactive" | "recording" = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((e: { data: { size: number } }) => void) | null = null;
  onstop: (() => void) | null = null;
  private _stream: { getTracks: () => { stop: () => void }[] };

  constructor(_stream: { getTracks: () => { stop: () => void }[] }) {
    this._stream = _stream;
  }

  start(_timeslice?: number) {
    this.state = "recording";
    // Simulate one data chunk immediately.
    if (this.ondataavailable) {
      this.ondataavailable({ data: { size: 100 } });
    }
  }

  stop() {
    this.state = "inactive";
    this._stream.getTracks().forEach((t) => t.stop());
    if (this.onstop) {
      this.onstop();
    }
  }
}

// ---------------------------------------------------------------------------
// MediaDevices mock
// ---------------------------------------------------------------------------

const mockGetUserMedia = vi.fn();

// Save original global values so they can be restored in afterEach and
// do not leak into other test files running in the same Vitest worker.
const _origMediaDevicesDescriptor = Object.getOwnPropertyDescriptor(
  global.navigator,
  "mediaDevices",
);
const _origCreateObjectURL = URL.createObjectURL;
const _origRevokeObjectURL = URL.revokeObjectURL;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeComment(
  overrides: Partial<MediaCommentResponse> = {},
): MediaCommentResponse {
  return {
    id: "mc-test-001",
    grade_id: "grade-test-001",
    s3_key: "media/teacher-001/grade-001/mc-test-001.webm",
    duration_seconds: 10,
    mime_type: "audio/webm",
    is_banked: false,
    created_at: "2026-04-24T00:00:00Z",
    ...overrides,
  };
}

function makeMockStream() {
  const track = { stop: vi.fn() };
  return {
    getTracks: () => [track],
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

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  // Default: no existing comments.
  mockListComments.mockResolvedValue([]);
  // Default: getUserMedia succeeds.
  const stream = makeMockStream();
  mockGetUserMedia.mockResolvedValue(stream);
  // Default: saveToBank succeeds.
  mockSaveToBank.mockResolvedValue({ id: "mc-test-001", is_banked: true });

  // Stub navigator.mediaDevices — restored in afterEach so the mutation does
  // not bleed into other test files in the same Vitest worker.
  Object.defineProperty(global.navigator, "mediaDevices", {
    value: { getUserMedia: mockGetUserMedia },
    writable: true,
    configurable: true,
  });

  // Stub URL methods — restored in afterEach.
  URL.createObjectURL = vi.fn(() => "blob:stub-url");
  URL.revokeObjectURL = vi.fn();

  // Install MockMediaRecorder globally — removed in afterEach.
  vi.stubGlobal("MediaRecorder", MockMediaRecorder);
});

afterEach(() => {
  vi.restoreAllMocks();
  // Remove the MediaRecorder stub set with vi.stubGlobal.
  vi.unstubAllGlobals();

  // Restore URL methods.
  URL.createObjectURL = _origCreateObjectURL;
  URL.revokeObjectURL = _origRevokeObjectURL;

  // Restore navigator.mediaDevices to its original state.
  if (_origMediaDevicesDescriptor) {
    Object.defineProperty(global.navigator, "mediaDevices", _origMediaDevicesDescriptor);
  } else {
    Object.defineProperty(global.navigator, "mediaDevices", {
      value: undefined,
      writable: true,
      configurable: true,
    });
  }
});

// ---------------------------------------------------------------------------
// Record / Stop toggle
// ---------------------------------------------------------------------------

describe("AudioRecorder — record/stop toggle", () => {
  it("shows a Record button initially", async () => {
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );
    expect(
      screen.getByRole("button", { name: /start recording/i }),
    ).toBeInTheDocument();
  });

  it("switches to Stop button while recording", async () => {
    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /start recording/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /stop recording/i }),
      ).toBeInTheDocument();
    });
  });

  it("returns to non-recording state after Stop is clicked", async () => {
    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /start recording/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /stop recording/i })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /stop recording/i }));

    // After stopping, the preview section with Save / Discard appears.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /save audio/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /discard/i })).toBeInTheDocument();
    });
  });

  it("shows the countdown timer while recording", async () => {
    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /start recording/i }));

    await waitFor(() => {
      // Countdown should start at 3:00.
      expect(screen.getByText("3:00")).toBeInTheDocument();
    });
  });

  it("shows permission error message when getUserMedia is denied", async () => {
    mockGetUserMedia.mockRejectedValueOnce(new Error("NotAllowedError"));
    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /start recording/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("alert"),
      ).toHaveTextContent(/microphone access was denied/i);
    });
  });

  it("shows not-supported error when MediaRecorder constructor throws", async () => {
    // Simulate a browser that does not support MediaRecorder (e.g. old Safari).
    vi.stubGlobal(
      "MediaRecorder",
      class {
        constructor() {
          throw new Error("MediaRecorder is not supported");
        }
      },
    );

    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /start recording/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("alert"),
      ).toHaveTextContent(/not supported in this browser/i);
    });
  });
});

// ---------------------------------------------------------------------------
// Save — calls upload then API / invalidates cache
// ---------------------------------------------------------------------------

describe("AudioRecorder — save flow", () => {
  it("calls uploadMediaComment with the gradeId, blob, and duration after saving", async () => {
    const newComment = makeComment({ id: "mc-new-001" });
    mockUpload.mockResolvedValueOnce(newComment);
    mockListComments
      .mockResolvedValueOnce([]) // initial load
      .mockResolvedValueOnce([newComment]); // after invalidation

    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    // Start then stop.
    await user.click(screen.getByRole("button", { name: /start recording/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /stop recording/i })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /stop recording/i }));

    // Wait for preview to appear.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /save audio/i })).toBeInTheDocument(),
    );

    // Save.
    await user.click(screen.getByRole("button", { name: /save audio/i }));

    await waitFor(() => {
      expect(mockUpload).toHaveBeenCalledTimes(1);
      const [calledGradeId, calledBlob, calledDuration] = mockUpload.mock.calls[0] as [
        string,
        Blob,
        number,
      ];
      expect(calledGradeId).toBe("grade-test-001");
      expect(calledBlob).toBeInstanceOf(Blob);
      expect(typeof calledDuration).toBe("number");
    });
  });

  it("hides preview and refreshes comment list after a successful save", async () => {
    const newComment = makeComment();
    mockUpload.mockResolvedValueOnce(newComment);
    mockListComments
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([newComment]);

    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    await user.click(screen.getByRole("button", { name: /start recording/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /stop recording/i })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /stop recording/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /save audio/i })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /save audio/i }));

    // Preview should disappear; Record button returns.
    await waitFor(() => {
      // The "Save audio comment" preview button should be gone.
      // (The "Save audio comment to reusable bank" button on existing rows
      // uses a different aria-label; we check the preview button specifically.)
      expect(
        screen.queryByRole("button", { name: /^save audio comment$/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /start recording/i }),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Delete — calls deleteMediaComment
// ---------------------------------------------------------------------------

describe("AudioRecorder — delete flow", () => {
  it("calls deleteMediaComment with the comment id when Delete is clicked", async () => {
    const comment = makeComment({ id: "mc-del-001" });
    mockListComments.mockResolvedValue([comment]);
    mockDelete.mockResolvedValueOnce(undefined);

    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    // Wait for the comment to appear.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /delete audio comment/i }),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /delete audio comment/i }));

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith("mc-del-001");
    });
  });

  it("does not show Delete button when isLocked=true", async () => {
    const comment = makeComment();
    mockListComments.mockResolvedValue([comment]);

    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={true} />,
      { wrapper },
    );

    await waitFor(() => {
      // The Play button should still appear; Delete should not.
      expect(
        screen.getByRole("button", { name: /play audio/i }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /delete audio/i }),
      ).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Playback URL — fetched on Play click
// ---------------------------------------------------------------------------

describe("AudioRecorder — playback URL", () => {
  it("calls getMediaCommentUrl with the comment id when Play is clicked", async () => {
    const comment = makeComment({ id: "mc-play-001" });
    mockListComments.mockResolvedValue([comment]);
    mockGetUrl.mockResolvedValueOnce({ url: "https://example.com/presigned" });

    const user = userEvent.setup();
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={false} />,
      { wrapper },
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /play audio/i }),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /play audio/i }));

    await waitFor(() => {
      expect(mockGetUrl).toHaveBeenCalledWith("mc-play-001");
    });
  });
});

// ---------------------------------------------------------------------------
// Locked state
// ---------------------------------------------------------------------------

describe("AudioRecorder — locked state", () => {
  it("does not render the Record button when isLocked=true", () => {
    mockListComments.mockResolvedValue([]);
    render(
      <AudioRecorder gradeId="grade-test-001" isLocked={true} />,
      { wrapper },
    );
    expect(
      screen.queryByRole("button", { name: /start recording/i }),
    ).not.toBeInTheDocument();
  });
});
