/**
 * Tests for WritingProcessPanel — M5-11 (Writing process visibility UI).
 *
 * Covers:
 * - Panel renders with process insight callout and summary stats
 * - Composition timeline renders session markers
 * - Gap blocks appear between sessions
 * - Paste-event flags appear with plain-language description
 * - Rapid-completion flags appear with plain-language description
 * - Snapshot viewer toggled by button (collapsed by default)
 * - Snapshot list renders with timestamps and word counts
 * - Selecting a snapshot shows a preview note
 * - Deselecting a snapshot (clicking again) hides the preview note
 * - WritingProcessPanelEmpty renders when no process data is available
 * - WritingProcessPanelSkeleton renders loading state with aria-busy
 * - Single-session insight string uses singular phrasing
 * - Multi-session insight string uses plural phrasing
 * - Paste event count shown in stats
 *
 * Security:
 * - No student PII in fixtures — synthetic IDs and times only.
 * - No credential-format strings in test data.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// No API calls are made in WritingProcessPanel; it is purely presentational.
// No mocks needed for API modules.

import {
  WritingProcessPanel,
  WritingProcessPanelEmpty,
  WritingProcessPanelSkeleton,
} from "@/components/grading/WritingProcessPanel";
import type { WritingProcessPanelProps } from "@/components/grading/WritingProcessPanel";
import type { ProcessSignalsResponse } from "@/lib/api/process-signals";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** Factory for ProcessSignalsResponse. No real student data. */
function makeSignals(
  overrides: Partial<ProcessSignalsResponse> = {},
): ProcessSignalsResponse {
  return {
    essay_id: "essay-test-001",
    essay_version_id: "ev-test-001",
    has_process_data: true,
    session_count: 1,
    active_writing_seconds: 900,
    total_elapsed_seconds: 1200,
    inter_session_gaps_seconds: [],
    sessions: [
      {
        session_index: 0,
        started_at: "2026-04-28T09:00:00Z",
        ended_at: "2026-04-28T09:15:00Z",
        duration_seconds: 900,
        snapshot_count: 10,
        word_count_start: 0,
        word_count_end: 350,
        words_added: 350,
      },
    ],
    paste_events: [],
    rapid_completion_events: [],
    computed_at: "2026-04-28T10:00:00Z",
    ...overrides,
  };
}

const twoSessionSignals: ProcessSignalsResponse = {
  essay_id: "essay-test-002",
  essay_version_id: "ev-test-002",
  has_process_data: true,
  session_count: 2,
  active_writing_seconds: 1800,
  total_elapsed_seconds: 90000,
  inter_session_gaps_seconds: [88200],
  sessions: [
    {
      session_index: 0,
      started_at: "2026-04-27T09:00:00Z",
      ended_at: "2026-04-27T09:15:00Z",
      duration_seconds: 900,
      snapshot_count: 12,
      word_count_start: 0,
      word_count_end: 250,
      words_added: 250,
    },
    {
      session_index: 1,
      started_at: "2026-04-28T09:30:00Z",
      ended_at: "2026-04-28T09:45:00Z",
      duration_seconds: 900,
      snapshot_count: 10,
      word_count_start: 250,
      word_count_end: 450,
      words_added: 200,
    },
  ],
  paste_events: [],
  rapid_completion_events: [],
  computed_at: "2026-04-28T10:00:00Z",
};

const signalsWithPaste: ProcessSignalsResponse = makeSignals({
  paste_events: [
    {
      snapshot_seq: 4,
      occurred_at: "2026-04-28T09:05:00Z",
      words_before: 50,
      words_after: 250,
      words_added: 200,
      session_index: 0,
    },
  ],
});

const signalsWithRapid: ProcessSignalsResponse = makeSignals({
  rapid_completion_events: [
    {
      session_index: 0,
      duration_seconds: 720,
      words_at_start: 50,
      words_at_end: 350,
      completion_fraction: 0.85,
    },
  ],
});

const sampleSnapshots = [
  { seq: 1, ts: "2026-04-28T09:00:12Z", word_count: 50 },
  { seq: 2, ts: "2026-04-28T09:05:00Z", word_count: 150 },
  { seq: 3, ts: "2026-04-28T09:10:00Z", word_count: 250 },
];

// ---------------------------------------------------------------------------
// WritingProcessPanel — rendering
// ---------------------------------------------------------------------------

describe("WritingProcessPanel — renders process signals", () => {
  it("renders the panel heading", () => {
    render(<WritingProcessPanel signals={makeSignals()} />);
    expect(
      screen.getByRole("region", { name: /writing process/i }),
    ).toBeInTheDocument();
  });

  it("renders the process insight callout", () => {
    render(<WritingProcessPanel signals={makeSignals()} />);
    expect(
      screen.getByTestId("process-insight-callout"),
    ).toBeInTheDocument();
  });

  it("shows single-session phrasing in insight callout", () => {
    render(<WritingProcessPanel signals={makeSignals({ session_count: 1 })} />);
    expect(
      screen.getByTestId("process-insight-callout"),
    ).toHaveTextContent(/written in a single session/i);
  });

  it("shows multi-session phrasing in insight callout", () => {
    render(<WritingProcessPanel signals={twoSessionSignals} />);
    expect(
      screen.getByTestId("process-insight-callout"),
    ).toHaveTextContent(/written across 2 sessions/i);
  });

  it("mentions paste events in insight callout when present", () => {
    render(<WritingProcessPanel signals={signalsWithPaste} />);
    expect(
      screen.getByTestId("process-insight-callout"),
    ).toHaveTextContent(/large content addition/i);
  });

  it("mentions rapid completion in insight callout when present", () => {
    render(<WritingProcessPanel signals={signalsWithRapid} />);
    expect(
      screen.getByTestId("process-insight-callout"),
    ).toHaveTextContent(/near-complete length in a short burst/i);
  });

  it("renders the composition timeline", () => {
    render(<WritingProcessPanel signals={makeSignals()} />);
    expect(screen.getByTestId("composition-timeline")).toBeInTheDocument();
  });

  it("renders a session block for each session", () => {
    render(<WritingProcessPanel signals={twoSessionSignals} />);
    expect(screen.getByTestId("session-block-0")).toBeInTheDocument();
    expect(screen.getByTestId("session-block-1")).toBeInTheDocument();
  });

  it("renders a gap block between sessions", () => {
    render(<WritingProcessPanel signals={twoSessionSignals} />);
    expect(screen.getByTestId("gap-block")).toBeInTheDocument();
  });

  it("renders session count stat", () => {
    render(<WritingProcessPanel signals={makeSignals({ session_count: 3 })} />);
    expect(screen.getByTestId("stat-session-count")).toHaveTextContent("3");
  });

  it("renders paste event count in stats", () => {
    render(<WritingProcessPanel signals={signalsWithPaste} />);
    expect(screen.getByTestId("stat-paste-events")).toHaveTextContent("1");
  });

  it("renders zero paste events in stats when none present", () => {
    render(<WritingProcessPanel signals={makeSignals()} />);
    expect(screen.getByTestId("stat-paste-events")).toHaveTextContent("0");
  });
});

// ---------------------------------------------------------------------------
// WritingProcessPanel — paste and rapid-completion flags
// ---------------------------------------------------------------------------

describe("WritingProcessPanel — process signal flags", () => {
  it("renders paste-event flags with plain-language description", () => {
    render(<WritingProcessPanel signals={signalsWithPaste} />);
    const flags = screen.getAllByTestId("paste-event-flag");
    expect(flags).toHaveLength(1);
    expect(flags[0]).toHaveTextContent(/large content addition/i);
    expect(flags[0]).toHaveTextContent(/may indicate pasted content/i);
    expect(flags[0]).toHaveTextContent(/warrants review/i);
  });

  it("renders rapid-completion flags with plain-language description", () => {
    render(<WritingProcessPanel signals={signalsWithRapid} />);
    const flags = screen.getAllByTestId("rapid-completion-flag");
    expect(flags).toHaveLength(1);
    expect(flags[0]).toHaveTextContent(/grew from \d+ to \d+ words/i);
    expect(flags[0]).toHaveTextContent(/unusually rapid completion/i);
    expect(flags[0]).toHaveTextContent(/warrants review/i);
  });

  it("renders no paste-event flags when none present", () => {
    render(<WritingProcessPanel signals={makeSignals()} />);
    expect(screen.queryAllByTestId("paste-event-flag")).toHaveLength(0);
  });

  it("renders no rapid-completion flags when none present", () => {
    render(<WritingProcessPanel signals={makeSignals()} />);
    expect(screen.queryAllByTestId("rapid-completion-flag")).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// WritingProcessPanel — snapshot viewer
// ---------------------------------------------------------------------------

describe("WritingProcessPanel — snapshot viewer", () => {
  it("snapshot viewer is collapsed by default", () => {
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    expect(screen.queryByTestId("snapshot-viewer")).not.toBeInTheDocument();
  });

  it("snapshot viewer opens when toggle is clicked", async () => {
    const user = userEvent.setup();
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    const toggle = screen.getByTestId("toggle-snapshot-viewer");
    await user.click(toggle);
    expect(screen.getByTestId("snapshot-viewer")).toBeInTheDocument();
  });

  it("snapshot viewer closes when toggle is clicked again", async () => {
    const user = userEvent.setup();
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    const toggle = screen.getByTestId("toggle-snapshot-viewer");
    await user.click(toggle);
    expect(screen.getByTestId("snapshot-viewer")).toBeInTheDocument();
    await user.click(toggle);
    expect(screen.queryByTestId("snapshot-viewer")).not.toBeInTheDocument();
  });

  it("toggle button has correct aria-expanded attribute when closed", () => {
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    expect(screen.getByTestId("toggle-snapshot-viewer")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("toggle button has correct aria-expanded attribute when open", async () => {
    const user = userEvent.setup();
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    await user.click(screen.getByTestId("toggle-snapshot-viewer"));
    expect(screen.getByTestId("toggle-snapshot-viewer")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("renders snapshot list items when viewer is open", async () => {
    const user = userEvent.setup();
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    await user.click(screen.getByTestId("toggle-snapshot-viewer"));
    expect(screen.getByTestId("snapshot-item-1")).toBeInTheDocument();
    expect(screen.getByTestId("snapshot-item-2")).toBeInTheDocument();
    expect(screen.getByTestId("snapshot-item-3")).toBeInTheDocument();
  });

  it("renders snapshot word counts in the list", async () => {
    const user = userEvent.setup();
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    await user.click(screen.getByTestId("toggle-snapshot-viewer"));
    expect(screen.getByText("50 words")).toBeInTheDocument();
    expect(screen.getByText("150 words")).toBeInTheDocument();
    expect(screen.getByText("250 words")).toBeInTheDocument();
  });

  it("selecting a snapshot shows a preview note", async () => {
    const user = userEvent.setup();
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    await user.click(screen.getByTestId("toggle-snapshot-viewer"));
    await user.click(screen.getByTestId("snapshot-item-2"));
    expect(screen.getByTestId("snapshot-preview-note")).toBeInTheDocument();
    expect(screen.getByTestId("snapshot-preview-note")).toHaveTextContent(
      /snapshot #2/i,
    );
  });

  it("deselecting a snapshot hides the preview note", async () => {
    const user = userEvent.setup();
    render(
      <WritingProcessPanel signals={makeSignals()} snapshots={sampleSnapshots} />,
    );
    await user.click(screen.getByTestId("toggle-snapshot-viewer"));
    await user.click(screen.getByTestId("snapshot-item-2"));
    expect(screen.getByTestId("snapshot-preview-note")).toBeInTheDocument();
    // Click again to deselect
    await user.click(screen.getByTestId("snapshot-item-2"));
    expect(screen.queryByTestId("snapshot-preview-note")).not.toBeInTheDocument();
  });

  it("shows 'no snapshots' message when snapshot list is empty", async () => {
    const user = userEvent.setup();
    render(<WritingProcessPanel signals={makeSignals()} snapshots={[]} />);
    await user.click(screen.getByTestId("toggle-snapshot-viewer"));
    expect(
      screen.getByText(/no snapshots recorded/i),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// WritingProcessPanelEmpty
// ---------------------------------------------------------------------------

describe("WritingProcessPanelEmpty", () => {
  it("renders the 'no process data' message", () => {
    render(<WritingProcessPanelEmpty />);
    expect(
      screen.getByText(/no writing process data is available/i),
    ).toBeInTheDocument();
  });

  it("explains that file-upload essays have no process data", () => {
    render(<WritingProcessPanelEmpty />);
    expect(
      screen.getByText(/file-upload essays do not include process signals/i),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// WritingProcessPanelSkeleton
// ---------------------------------------------------------------------------

describe("WritingProcessPanelSkeleton", () => {
  it("renders loading state with aria-busy", () => {
    render(<WritingProcessPanelSkeleton />);
    expect(
      screen.getByRole("region", { name: /loading writing process/i }),
    ).toHaveAttribute("aria-busy", "true");
  });
});
