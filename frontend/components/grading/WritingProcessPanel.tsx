"use client";

/**
 * WritingProcessPanel — composition timeline and process signals (M5-11).
 *
 * Displays writing-process intelligence inside the essay review interface:
 * - Process insight callout summarising key signals in plain language
 * - Visual composition timeline with session markers
 * - Paste-event flags and rapid-completion indicators
 * - Version snapshot viewer listing snapshot history with timestamps and word counts
 *
 * Design principles:
 * - ALL language frames signals as indicators, not definitive judgments.
 *   e.g. "Content may have been pasted" NOT "Student cheated".
 * - The panel only appears when process data is available (browser-composed essays).
 * - File-upload essays show a clear "no process data" explanation.
 * - This panel is informational; the teacher always decides next steps.
 *
 * Security:
 * - No student PII is logged; only entity IDs appear in error paths.
 * - API error messages are mapped to static strings; raw server text is never shown.
 */

import { useState, useMemo } from "react";
import type {
  ProcessSignalsResponse,
  SessionSegment,
  PasteEvent,
  RapidCompletionEvent,
} from "@/lib/api/process-signals";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format seconds as a human-readable duration string, e.g. "1h 15m" or "45m". */
function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  if (minutes > 0) return `${minutes}m`;
  return `${Math.round(totalSeconds)}s`;
}

/** Format a gap in seconds as a human-readable string, e.g. "1 day", "3 hours". */
function formatGap(gapSeconds: number): string {
  const days = Math.floor(gapSeconds / 86400);
  const hours = Math.floor((gapSeconds % 86400) / 3600);
  const minutes = Math.floor((gapSeconds % 3600) / 60);
  if (days > 0) return days === 1 ? "1 day" : `${days} days`;
  if (hours > 0) return hours === 1 ? "1 hour" : `${hours} hours`;
  return minutes === 1 ? "1 minute" : `${minutes} minutes`;
}

/** Format an ISO timestamp for display, e.g. "Apr 28, 10:05 AM". */
function formatTimestamp(ts: string): string {
  return new Date(ts).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Build a plain-language process insight summary from the signal data.
 * Always framed as an indicator — never a finding.
 */
function buildInsightSummary(signals: ProcessSignalsResponse): string {
  const { session_count, active_writing_seconds, paste_events, rapid_completion_events } =
    signals;

  const parts: string[] = [];

  if (session_count === 1) {
    parts.push(
      `Written in a single session (${formatDuration(active_writing_seconds)} active writing time).`,
    );
  } else {
    parts.push(
      `Written across ${session_count} sessions (${formatDuration(active_writing_seconds)} active writing time).`,
    );
  }

  if (paste_events.length === 1) {
    parts.push("1 large content addition detected — may indicate pasted content.");
  } else if (paste_events.length > 1) {
    parts.push(
      `${paste_events.length} large content additions detected — may indicate pasted content.`,
    );
  }

  if (rapid_completion_events.length > 0) {
    parts.push("Essay reached near-complete length in a short burst — warrants review.");
  }

  return parts.join(" ");
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Session block inside the composition timeline. */
function SessionBlock({
  session,
  pasteEvents,
  rapidEvents,
  totalSessions,
}: {
  session: SessionSegment;
  pasteEvents: PasteEvent[];
  rapidEvents: RapidCompletionEvent[];
  totalSessions: number;
}) {
  const sessionPastes = pasteEvents.filter(
    (e) => e.session_index === session.session_index,
  );
  const sessionRapid = rapidEvents.filter(
    (e) => e.session_index === session.session_index,
  );
  const hasFlags = sessionPastes.length > 0 || sessionRapid.length > 0;

  return (
    <div
      className="relative flex gap-3"
      data-testid={`session-block-${session.session_index}`}
    >
      {/* Timeline spine connector + marker */}
      <div className="flex flex-col items-center">
        <div
          className={`mt-0.5 h-4 w-4 flex-shrink-0 rounded-full border-2 ${
            hasFlags
              ? "border-amber-500 bg-amber-100"
              : "border-blue-400 bg-blue-50"
          }`}
          aria-hidden="true"
        />
        {session.session_index < totalSessions - 1 && (
          <div className="w-0.5 flex-1 bg-gray-200" aria-hidden="true" />
        )}
      </div>

      {/* Session card */}
      <div className="mb-4 flex-1 rounded-md border border-gray-200 bg-white p-3 shadow-sm">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs font-semibold text-gray-700">
              Session {session.session_index + 1}
            </p>
            <p className="text-xs text-gray-500">
              {formatTimestamp(session.started_at)} &mdash;{" "}
              {new Date(session.ended_at).toLocaleTimeString(undefined, {
                hour: "numeric",
                minute: "2-digit",
              })}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs font-medium text-gray-700">
              {formatDuration(session.duration_seconds)}
            </p>
            <p className="text-xs text-gray-400">
              +{session.words_added} words
            </p>
          </div>
        </div>

        {/* Paste event flags */}
        {sessionPastes.map((paste) => (
          <div
            key={`paste-${paste.snapshot_seq}`}
            className="mt-2 flex items-start gap-1.5 rounded bg-amber-50 px-2 py-1.5"
            role="note"
            aria-label="Paste event indicator"
            data-testid="paste-event-flag"
          >
            <svg
              aria-hidden="true"
              className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
              />
            </svg>
            <p className="text-xs text-amber-800">
              Large content addition at{" "}
              {formatTimestamp(paste.occurred_at)} (+{paste.words_added} words).
              May indicate pasted content — warrants review.
            </p>
          </div>
        ))}

        {/* Rapid completion flags */}
        {sessionRapid.map((evt) => (
          <div
            key={`rapid-${evt.snapshot_seq}`}
            className="mt-2 flex items-start gap-1.5 rounded bg-orange-50 px-2 py-1.5"
            role="note"
            aria-label="Rapid completion indicator"
            data-testid="rapid-completion-flag"
          >
            <svg
              aria-hidden="true"
              className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-orange-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
            <p className="text-xs text-orange-800">
              Essay reached near-complete length in{" "}
              {formatDuration(evt.duration_seconds)} — unusually rapid
              completion. Warrants review.
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Gap block displayed between two sessions on the timeline. */
function GapBlock({ gapSeconds }: { gapSeconds: number }) {
  return (
    <div className="relative flex gap-3" data-testid="gap-block">
      <div className="flex flex-col items-center">
        <div className="w-0.5 flex-1 bg-gray-200" aria-hidden="true" />
      </div>
      <div className="mb-2 flex-1 py-1">
        <p className="text-xs italic text-gray-400">
          {formatGap(gapSeconds)} gap between sessions
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Snapshot viewer
// ---------------------------------------------------------------------------

export interface SnapshotItem {
  seq: number;
  ts: string;
  word_count: number;
}

function SnapshotViewer({ snapshots }: { snapshots: SnapshotItem[] }) {
  const [selected, setSelected] = useState<number | null>(null);

  // Memoize the selected snapshot to avoid a linear search on every render.
  const selectedSnapshot = useMemo(
    () => (selected !== null ? snapshots.find((s) => s.seq === selected) : undefined),
    [selected, snapshots],
  );

  if (snapshots.length === 0) {
    return (
      <p className="text-xs text-gray-400">
        No snapshots recorded for this essay.
      </p>
    );
  }

  return (
    <div>
      <p className="mb-2 text-xs text-gray-500">
        {snapshots.length} snapshot{snapshots.length !== 1 ? "s" : ""} recorded.
        Select a point to view essay state at that time.
      </p>
      <ul
        className="max-h-48 overflow-y-auto rounded-md border border-gray-200"
        aria-label="Essay snapshots"
      >
        {[...snapshots].reverse().map((snap) => (
          <li key={snap.seq} className="border-b border-gray-100 last:border-0">
            <button
              type="button"
              aria-pressed={selected === snap.seq}
              onClick={() =>
                setSelected((prev) => (prev === snap.seq ? null : snap.seq))
              }
              className={`flex w-full items-center justify-between px-3 py-2 text-left text-xs hover:bg-gray-50 focus:outline-none focus:ring-1 focus:ring-inset focus:ring-blue-500 ${
                selected === snap.seq
                  ? "bg-blue-50 font-medium text-blue-700"
                  : "text-gray-600"
              }`}
              data-testid={`snapshot-item-${snap.seq}`}
            >
              <span>{formatTimestamp(snap.ts)}</span>
              <span className="text-gray-400">{snap.word_count} words</span>
            </button>
          </li>
        ))}
      </ul>

      {selected !== null && (
        <div
          className="mt-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2"
          role="status"
          data-testid="snapshot-preview-note"
        >
          <p className="text-xs text-blue-800">
            Snapshot #{selected} selected ({selectedSnapshot?.word_count ?? 0} words).
            Full snapshot content preview is available in the writing interface.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Process insight callout
// ---------------------------------------------------------------------------

function ProcessInsightCallout({ signals }: { signals: ProcessSignalsResponse }) {
  const summary = buildInsightSummary(signals);
  const hasFlags =
    signals.paste_events.length > 0 || signals.rapid_completion_events.length > 0;

  return (
    <div
      role="note"
      aria-label="Process insight summary"
      className={`rounded-md border px-3 py-2.5 ${
        hasFlags
          ? "border-amber-200 bg-amber-50"
          : "border-blue-200 bg-blue-50"
      }`}
      data-testid="process-insight-callout"
    >
      <p
        className={`text-xs font-semibold ${
          hasFlags ? "text-amber-800" : "text-blue-800"
        }`}
      >
        Writing process summary
      </p>
      <p
        className={`mt-0.5 text-xs ${
          hasFlags ? "text-amber-700" : "text-blue-700"
        }`}
      >
        {summary}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface WritingProcessPanelProps {
  /** The process signals data returned by GET /essays/{essayId}/process-signals. */
  signals: ProcessSignalsResponse;
  /**
   * Snapshot metadata list (from GET /essays/{essayId}/snapshots).
   * Pass an empty array or omit if not yet loaded.
   */
  snapshots?: SnapshotItem[];
}

// ---------------------------------------------------------------------------
// WritingProcessPanel — main component
// ---------------------------------------------------------------------------

export function WritingProcessPanel({
  signals,
  snapshots = [],
}: WritingProcessPanelProps) {
  const [showSnapshots, setShowSnapshots] = useState(false);

  return (
    <div
      role="region"
      className="rounded-lg border border-gray-200 bg-white shadow-sm"
      aria-label="Writing process"
    >
      {/* Header */}
      <div className="border-b border-gray-200 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900">Writing Process</h3>
        <p className="mt-0.5 text-xs text-gray-400">
          These signals describe how the essay developed over time. They are
          indicators only — not definitive findings.
        </p>
      </div>

      <div className="space-y-4 p-4">
        {/* Process insight callout */}
        <ProcessInsightCallout signals={signals} />

        {/* Summary stats */}
        <div className="grid grid-cols-3 gap-2">
          <div className="rounded-md border border-gray-100 bg-gray-50 px-2 py-2 text-center">
            <p
              className="text-lg font-bold text-gray-800"
              data-testid="stat-session-count"
            >
              {signals.session_count}
            </p>
            <p className="text-xs text-gray-500">
              session{signals.session_count !== 1 ? "s" : ""}
            </p>
          </div>
          <div className="rounded-md border border-gray-100 bg-gray-50 px-2 py-2 text-center">
            <p
              className="text-lg font-bold text-gray-800"
              data-testid="stat-active-time"
            >
              {formatDuration(signals.active_writing_seconds)}
            </p>
            <p className="text-xs text-gray-500">active time</p>
          </div>
          <div className="rounded-md border border-gray-100 bg-gray-50 px-2 py-2 text-center">
            <p
              className={`text-lg font-bold ${
                signals.paste_events.length > 0
                  ? "text-amber-700"
                  : "text-gray-800"
              }`}
              data-testid="stat-paste-events"
            >
              {signals.paste_events.length}
            </p>
            <p className="text-xs text-gray-500">
              paste event{signals.paste_events.length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>

        {/* Composition timeline */}
        <div>
          <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Composition Timeline
          </p>
          {signals.sessions.length === 0 ? (
            <p className="text-xs text-gray-400">
              No session data available.
            </p>
          ) : (
            <div
              aria-label="Composition timeline"
              data-testid="composition-timeline"
            >
              {signals.sessions.map((session, idx) => (
                <div key={session.session_index}>
                  <SessionBlock
                    session={session}
                    pasteEvents={signals.paste_events}
                    rapidEvents={signals.rapid_completion_events}
                    totalSessions={signals.sessions.length}
                  />
                  {idx < signals.sessions.length - 1 &&
                    signals.inter_session_gaps_seconds[idx] != null && (
                      <GapBlock
                        gapSeconds={signals.inter_session_gaps_seconds[idx]}
                      />
                    )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Version snapshot viewer (collapsible) */}
        <div>
          <button
            type="button"
            onClick={() => setShowSnapshots((prev) => !prev)}
            className="flex w-full items-center justify-between rounded-md px-0 py-1 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-expanded={showSnapshots}
            aria-controls="snapshot-viewer"
            data-testid="toggle-snapshot-viewer"
          >
            <span>Version Snapshots</span>
            <svg
              aria-hidden="true"
              className={`h-4 w-4 transition-transform ${
                showSnapshots ? "rotate-180" : ""
              }`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 9l-7 7-7-7"
              />
            </svg>
          </button>

          {showSnapshots && (
            <div
              id="snapshot-viewer"
              className="mt-2"
              data-testid="snapshot-viewer"
            >
              <SnapshotViewer snapshots={snapshots} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WritingProcessPanelSkeleton — shown while loading
// ---------------------------------------------------------------------------

export function WritingProcessPanelSkeleton() {
  return (
    <div
      role="region"
      className="animate-pulse rounded-lg border border-gray-200 bg-white shadow-sm"
      aria-busy="true"
      aria-label="Loading writing process"
    >
      <div className="border-b border-gray-200 px-4 py-3">
        <div className="h-4 w-36 rounded bg-gray-200" />
      </div>
      <div className="space-y-3 p-4">
        <div className="h-12 rounded-md bg-gray-100" />
        <div className="grid grid-cols-3 gap-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-14 rounded-md bg-gray-100" />
          ))}
        </div>
        <div className="h-24 rounded-md bg-gray-100" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WritingProcessPanelEmpty — shown for file-upload essays (no process data)
// ---------------------------------------------------------------------------

export function WritingProcessPanelEmpty() {
  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-200 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900">Writing Process</h3>
      </div>
      <div className="p-6 text-center">
        <svg
          aria-hidden="true"
          className="mx-auto mb-3 h-8 w-8 text-gray-300"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
          />
        </svg>
        <p className="text-sm text-gray-500">
          No writing process data is available for this essay.
        </p>
        <p className="mt-1 text-xs text-gray-400">
          Writing process data is only captured for essays composed within the
          system. File-upload essays do not include process signals.
        </p>
      </div>
    </div>
  );
}
