/**
 * Tests for VideoRecorder — M4.11 (Video comment recording).
 *
 * Covers (per acceptance criteria):
 * - MIME type is set to video/webm for normal webcam recording.
 * - Screen share toggle causes getDisplayMedia to be called instead of
 *   getUserMedia for the video track.
 * - Permission denied (getUserMedia rejected) shows a static error message
 *   and offers an audio-only fallback.
 * - Permission denied for both video and audio shows a combined error message.
 * - Record / Stop toggle starts and stops MediaRecorder.
 * - Max 3-minute limit is reflected in the countdown.
 * - Save calls uploadMediaComment then invalidates query cache.
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

vi.mock("@/lib/api/media-comments", () => ({
  uploadMediaComment: (...args: unknown[]) => mockUpload(...args),
  listGradeMediaComments: (...args: unknown[]) => mockListComments(...args),
  deleteMediaComment: (...args: unknown[]) => mockDelete(...args),
  getMediaCommentUrl: (...args: unknown[]) => mockGetUrl(...args),
}));

import { VideoRecorder } from "@/components/grading/VideoRecorder";
import type { MediaCommentResponse } from "@/lib/api/media-comments";

// ---------------------------------------------------------------------------
// MediaRecorder mock
// ---------------------------------------------------------------------------

class MockMediaRecorder {
  state: "inactive" | "recording" = "inactive";
  mimeType = "video/webm";
  ondataavailable: ((e: { data: { size: number } }) => void) | null = null;
  onstop: (() => void) | null = null;
  private _stream: { getTracks: () => { stop: () => void }[] };

  constructor(
    _stream: { getTracks: () => { stop: () => void }[] },
    options?: { mimeType?: string },
  ) {
    this._stream = _stream;
    if (options?.mimeType) {
      this.mimeType = options.mimeType;
    }
  }

  static isTypeSupported(mimeType: string): boolean {
    return mimeType === "video/webm" || mimeType === "audio/webm";
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  start(..._args: unknown[]) {
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
const mockGetDisplayMedia = vi.fn();

// Save original global values so they can be restored in afterEach.
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
    id: "vc-test-001",
    grade_id: "grade-test-001",
    s3_key: "media/teacher-001/grade-001/vc-test-001.webm",
    duration_seconds: 15,
    mime_type: "video/webm",
    created_at: "2026-04-24T00:00:00Z",
    ...overrides,
  };
}

function makeMockStream() {
  const track = { stop: vi.fn() };
  return {
    getTracks: () => [track],
    getVideoTracks: () => [track],
    getAudioTracks: () => [track],
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
  // Default: getUserMedia and getDisplayMedia succeed.
  const stream = makeMockStream();
  mockGetUserMedia.mockResolvedValue(stream);
  mockGetDisplayMedia.mockResolvedValue(stream);

  // Stub navigator.mediaDevices.
  Object.defineProperty(global.navigator, "mediaDevices", {
    value: {
      getUserMedia: mockGetUserMedia,
      getDisplayMedia: mockGetDisplayMedia,
    },
    writable: true,
    configurable: true,
  });

  // Stub URL methods.
  URL.createObjectURL = vi.fn(() => "blob:stub-url");
  URL.revokeObjectURL = vi.fn();

  // Install MockMediaRecorder globally.
  vi.stubGlobal("MediaRecorder", MockMediaRecorder);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();

  // Restore URL methods.
  URL.createObjectURL = _origCreateObjectURL;
  URL.revokeObjectURL = _origRevokeObjectURL;

  // Restore navigator.mediaDevices.
  if (_origMediaDevicesDescriptor) {
    Object.defineProperty(
      global.navigator,
      "mediaDevices",
      _origMediaDevicesDescriptor,
    );
  } else {
    Object.defineProperty(global.navigator, "mediaDevices", {
      value: undefined,
      writable: true,
      configurable: true,
    });
  }
});

// ---------------------------------------------------------------------------
// MIME type — video/webm set correctly for webcam recording
// ---------------------------------------------------------------------------

describe("VideoRecorder — MIME type", () => {
  it("passes a video/webm blob to uploadMediaComment after recording", async () => {
    const newComment = makeComment({ id: "vc-mime-001" });
    mockUpload.mockResolvedValueOnce(newComment);

    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    // Start then stop.
    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /stop recording/i }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /stop recording/i }));

    // Wait for the preview/save section.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /save video/i }),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /save video/i }));

    await waitFor(() => {
      expect(mockUpload).toHaveBeenCalledTimes(1);
      const [, blob] = mockUpload.mock.calls[0] as [string, Blob, number];
      // The blob should have the video/webm MIME type.
      expect(blob.type).toBe("video/webm");
    });
  });

  it("calls getUserMedia with video:true and audio:true for webcam recording", async () => {
    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      expect(mockGetUserMedia).toHaveBeenCalledWith({
        video: true,
        audio: true,
      });
    });
  });
});

// ---------------------------------------------------------------------------
// Screen share toggle — getDisplayMedia called when toggle is enabled
// ---------------------------------------------------------------------------

describe("VideoRecorder — screen share toggle", () => {
  it("renders the screen share checkbox when not recording", () => {
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    expect(
      screen.getByRole("checkbox", { name: /share screen instead of webcam/i }),
    ).toBeInTheDocument();
  });

  it("calls getDisplayMedia when screen share is enabled and recording starts", async () => {
    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    // Enable screen share.
    const checkbox = screen.getByRole("checkbox", {
      name: /share screen instead of webcam/i,
    });
    await user.click(checkbox);
    expect(checkbox).toBeChecked();

    // Start recording.
    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      expect(mockGetDisplayMedia).toHaveBeenCalledWith({ video: true });
    });
  });

  it("does not call getUserMedia with video when screen share is enabled", async () => {
    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    // Enable screen share.
    await user.click(
      screen.getByRole("checkbox", { name: /share screen instead of webcam/i }),
    );

    // Start recording.
    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      // getUserMedia should only be called for audio (not for video:true).
      const videoCall = mockGetUserMedia.mock.calls.find(
        (call) => (call[0] as { video?: boolean })?.video === true,
      );
      expect(videoCall).toBeUndefined();
    });
  });

  it("does not render the screen share toggle when isLocked=true", () => {
    render(<VideoRecorder gradeId="grade-test-001" isLocked={true} />, {
      wrapper,
    });

    expect(
      screen.queryByRole("checkbox", { name: /share screen instead of webcam/i }),
    ).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Permission denied — error state and audio-only fallback
// ---------------------------------------------------------------------------

describe("VideoRecorder — permission denied", () => {
  it("shows a camera-denied error and falls back to audio-only when getUserMedia(video) is denied", async () => {
    // Reject the first getUserMedia (video+audio), succeed on second (audio only).
    const audioOnlyStream = makeMockStream();
    const notAllowedError = Object.assign(new Error("Permission denied"), {
      name: "NotAllowedError",
    });
    mockGetUserMedia
      .mockRejectedValueOnce(notAllowedError)
      .mockResolvedValueOnce(audioOnlyStream);

    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /camera access was denied.*recording audio only/i,
      );
    });

    // Should still be recording (audio-only).
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /stop recording/i }),
      ).toBeInTheDocument();
    });
  });

  it("shows a combined error when both video and audio are denied", async () => {
    const notAllowedError = Object.assign(new Error("Permission denied"), {
      name: "NotAllowedError",
    });
    mockGetUserMedia.mockRejectedValue(notAllowedError);

    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /microphone and camera access were denied/i,
      );
    });

    // Should NOT be recording.
    expect(
      screen.queryByRole("button", { name: /stop recording/i }),
    ).not.toBeInTheDocument();
  });

  it("shows a screen share denied error when getDisplayMedia is rejected", async () => {
    const notAllowedError = Object.assign(new Error("Permission denied"), {
      name: "NotAllowedError",
    });
    mockGetDisplayMedia.mockRejectedValueOnce(notAllowedError);

    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    // Enable screen share.
    await user.click(
      screen.getByRole("checkbox", { name: /share screen instead of webcam/i }),
    );

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /screen share access was denied/i,
      );
    });
  });

  it("shows not-supported error when MediaRecorder constructor throws", async () => {
    vi.stubGlobal(
      "MediaRecorder",
      class {
        static isTypeSupported() {
          return false;
        }
        constructor() {
          throw new Error("MediaRecorder is not supported");
        }
      },
    );

    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /not supported in this browser/i,
      );
    });
  });
});

// ---------------------------------------------------------------------------
// Record / Stop toggle
// ---------------------------------------------------------------------------

describe("VideoRecorder — record/stop toggle", () => {
  it("shows a Record button initially", async () => {
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });
    expect(
      screen.getByRole("button", { name: /start recording video/i }),
    ).toBeInTheDocument();
  });

  it("switches to Stop button while recording", async () => {
    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /stop recording/i }),
      ).toBeInTheDocument();
    });
  });

  it("returns to non-recording state with save/discard controls after Stop", async () => {
    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /stop recording/i }),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /stop recording/i }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /save video/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /discard/i }),
      ).toBeInTheDocument();
    });
  });

  it("shows the countdown timer while recording", async () => {
    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );

    await waitFor(() => {
      // Countdown should start at 3:00.
      expect(screen.getByText("3:00")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Save — calls upload then invalidates cache
// ---------------------------------------------------------------------------

describe("VideoRecorder — save flow", () => {
  it("hides preview and shows Record button after a successful save", async () => {
    const newComment = makeComment();
    mockUpload.mockResolvedValueOnce(newComment);
    mockListComments
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([newComment]);

    const user = userEvent.setup();
    render(<VideoRecorder gradeId="grade-test-001" isLocked={false} />, {
      wrapper,
    });

    await user.click(
      screen.getByRole("button", { name: /start recording video/i }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /stop recording/i }),
      ).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: /stop recording/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /save video/i }),
      ).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: /save video/i }));

    // Preview should disappear; Record button returns.
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /save video/i }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /start recording video/i }),
      ).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Locked state
// ---------------------------------------------------------------------------

describe("VideoRecorder — locked state", () => {
  it("does not render the Record button when isLocked=true", () => {
    mockListComments.mockResolvedValue([]);
    render(<VideoRecorder gradeId="grade-test-001" isLocked={true} />, {
      wrapper,
    });
    expect(
      screen.queryByRole("button", { name: /start recording video/i }),
    ).not.toBeInTheDocument();
  });

  it("does not show Delete button when isLocked=true", async () => {
    const comment = makeComment();
    mockListComments.mockResolvedValue([comment]);

    render(<VideoRecorder gradeId="grade-test-001" isLocked={true} />, {
      wrapper,
    });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /play video/i }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /delete video/i }),
      ).not.toBeInTheDocument();
    });
  });
});
