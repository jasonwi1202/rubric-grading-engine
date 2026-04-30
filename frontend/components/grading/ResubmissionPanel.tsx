"use client";

/**
 * ResubmissionPanel — resubmission review UI (M6-12).
 *
 * Displays the revision comparison for an essay that has been resubmitted
 * and re-graded.  Intended to appear inside the essay review page when a
 * revision comparison exists for the essay.
 *
 * Features:
 * - Version history strip: shows base (v1) and revised (v2+) version metadata
 *   with submission dates and word counts; the active version is highlighted.
 * - Low-effort warning banner when `is_low_effort` is true.
 * - Total score delta with colour-coded badge (+/−).
 * - Criterion-level score delta table: base score, revised score, delta.
 * - Side-by-side content diff placeholder (essay content API not yet available).
 * - Feedback-addressed indicators: per-criterion LLM assessment of whether the
 *   student's revision addressed the feedback given on the base submission.
 *   Hidden when `feedback_addressed` is null (LLM step skipped or failed).
 *
 * Design principles:
 * - Teacher always decides; this panel is informational only.
 * - All language is neutral: "revision", not "improvement"; "change", not "cheat".
 * - Low-effort flag is framed as a signal, not a finding.
 *
 * Security:
 * - No student PII in log output — only entity IDs.
 * - API error messages are static strings; raw server text is never rendered.
 */

import { useState } from "react";
import type {
  RevisionComparisonResponse,
  CriterionDeltaResponse,
  FeedbackAddressedItemResponse,
} from "@/lib/api/resubmission";
import type { RubricSnapshotCriterion } from "@/lib/rubric/parseRubricSnapshot";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format an ISO datetime string as a short date + time, e.g. "Apr 30, 2:15 PM". */
function formatDate(iso: string): string {
  const date = new Date(iso);
  if (isNaN(date.getTime())) return "Date unavailable";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Format a numeric score delta as "+N", "−N", or "0". */
function formatDelta(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `\u2212${Math.abs(delta)}`; // minus sign, not hyphen
  return "0";
}

/** Tailwind classes for a score delta badge based on sign. */
function deltaBadgeClass(delta: number): string {
  if (delta > 0) return "bg-green-50 text-green-700 ring-1 ring-green-200";
  if (delta < 0) return "bg-red-50 text-red-700 ring-1 ring-red-200";
  return "bg-gray-50 text-gray-600 ring-1 ring-gray-200";
}

/** Tailwind text colour for a score delta value. */
function deltaTextClass(delta: number): string {
  if (delta > 0) return "text-green-700";
  if (delta < 0) return "text-red-600";
  return "text-gray-500";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Version strip button — shows version label, date, and word count. */
function VersionButton({
  label,
  submittedAt,
  wordCount,
  isActive,
  onClick,
}: {
  label: string;
  submittedAt: string;
  wordCount: number;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isActive}
      className={`flex-1 rounded-lg border px-3 py-2 text-left text-xs transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 ${
        isActive
          ? "border-blue-500 bg-blue-50 text-blue-800"
          : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
      }`}
    >
      <p className="font-semibold">{label}</p>
      <p className="mt-0.5 text-gray-500">{formatDate(submittedAt)}</p>
      {wordCount > 0 ? (
        <p className="mt-0.5 text-gray-400">{wordCount.toLocaleString()} words</p>
      ) : (
        <p className="mt-0.5 text-gray-300">Word count unavailable</p>
      )}
    </button>
  );
}

/** Low-effort warning banner. */
function LowEffortBanner({ reasons }: { reasons: string[] }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3"
    >
      <p className="text-sm font-semibold text-amber-800">
        ⚠ Low-effort revision detected
      </p>
      <p className="mt-1 text-xs text-amber-700">
        Heuristics suggest this revision may not reflect substantive revision.
        Review the changes carefully before updating the grade.
      </p>
      {reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {reasons.map((reason, i) => (
            <li key={i} className="text-xs text-amber-700">
              • {reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Score delta summary row. */
function ScoreDeltaSummary({ delta }: { delta: number }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-4 py-3">
      <p className="text-sm font-semibold text-gray-700">Total score change</p>
      <span
        className={`rounded-full px-3 py-1 text-sm font-bold ${deltaBadgeClass(delta)}`}
        aria-label={`Total score delta: ${formatDelta(delta)}`}
      >
        {formatDelta(delta)}
      </span>
    </div>
  );
}

/** Per-criterion score delta table row. */
function CriterionDeltaRow({
  delta,
  criterionName,
  feedbackItem,
}: {
  delta: CriterionDeltaResponse;
  criterionName: string;
  feedbackItem: FeedbackAddressedItemResponse | undefined;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasFeedback = feedbackItem !== undefined;

  return (
    <li className="rounded-lg border border-gray-100 bg-white px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        {/* Criterion name */}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-800 capitalize">
            {criterionName}
          </p>

          {/* Score line */}
          <p className="mt-0.5 text-xs text-gray-500">
            <span className="tabular-nums">{delta.base_score}</span>
            <span aria-hidden="true" className="mx-1">
              →
            </span>
            <span className="tabular-nums">{delta.revised_score}</span>
          </p>
        </div>

        {/* Delta badge */}
        <span
          className={`shrink-0 rounded-full px-2.5 py-0.5 text-sm font-semibold tabular-nums ${deltaTextClass(delta.delta)}`}
          aria-label={`Score delta: ${formatDelta(delta.delta)}`}
        >
          {formatDelta(delta.delta)}
        </span>
      </div>

      {/* Feedback-addressed indicator */}
      {hasFeedback && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            aria-expanded={expanded}
            className="flex w-full items-center gap-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
          >
            <span
              aria-hidden="true"
              className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                feedbackItem.addressed ? "bg-green-500" : "bg-red-400"
              }`}
            />
            <span
              className={
                feedbackItem.addressed ? "text-green-700" : "text-red-600"
              }
            >
              Feedback{" "}
              {feedbackItem.addressed ? "addressed" : "not addressed"}
            </span>
            <span aria-hidden="true" className="ml-auto text-gray-400">
              {expanded ? "▲" : "▼"}
            </span>
          </button>

          {expanded && (
            <div className="mt-2 space-y-2 rounded-md bg-gray-50 p-3 text-xs text-gray-600">
              <div>
                <p className="font-medium text-gray-700">Feedback given:</p>
                <p className="mt-0.5 italic">{feedbackItem.feedback_given}</p>
              </div>
              <div>
                <p className="font-medium text-gray-700">Assessment:</p>
                <p className="mt-0.5">{feedbackItem.detail}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

/** Side-by-side content diff placeholder.
 *
 * `activeVersion` drives which column header is highlighted to reflect the
 * version the teacher has selected via the version strip buttons.  The full
 * diff content will render here once a dedicated essay content endpoint is
 * available; for now both columns show a "coming soon" placeholder.
 */
function DiffPlaceholder({ activeVersion }: { activeVersion: "base" | "revised" }) {
  const baseActive = activeVersion === "base";
  const revisedActive = activeVersion === "revised";

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="grid grid-cols-2 divide-x divide-gray-200">
        {/* Base version */}
        <div className={baseActive ? "ring-2 ring-inset ring-blue-400 rounded-l-lg" : ""}>
          <div className="border-b border-gray-200 px-3 py-2">
            <p className={`text-xs font-semibold ${baseActive ? "text-blue-700" : "text-gray-600"}`}>
              Original submission
            </p>
          </div>
          <div className="flex flex-col items-center justify-center py-8 text-center px-4">
            <svg
              aria-hidden="true"
              className="mb-2 h-6 w-6 text-gray-300"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <p className="text-xs text-gray-400">
              Content preview coming soon
            </p>
          </div>
        </div>

        {/* Revised version */}
        <div className={revisedActive ? "ring-2 ring-inset ring-blue-400 rounded-r-lg" : ""}>
          <div className="border-b border-gray-200 px-3 py-2">
            <p className={`text-xs font-semibold ${revisedActive ? "text-blue-700" : "text-gray-600"}`}>
              Revised submission
            </p>
          </div>
          <div className="flex flex-col items-center justify-center py-8 text-center px-4">
            <svg
              aria-hidden="true"
              className="mb-2 h-6 w-6 text-gray-300"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <p className="text-xs text-gray-400">
              Content preview coming soon
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ResubmissionPanelProps {
  /** The revision comparison data from the API. */
  comparison: RevisionComparisonResponse;
  /**
   * Rubric criteria from the assignment snapshot — used to look up criterion
   * names by ID.  Pass an empty array when criteria are unavailable; the panel
   * will fall back to showing the raw criterion UUID.
   */
  criteria: RubricSnapshotCriterion[];
  /**
   * Submission date for the base version (v1), used in the version strip.
   * When null/undefined the strip falls back to `comparison.created_at`.
   *
   * NOTE (M6-12): The backend does not yet expose per-version submission dates
   * in the revision-comparison response.  These props are intentional placeholders
   * for a future milestone that adds a dedicated essay-versions list endpoint.
   */
  baseVersionSubmittedAt?: string | null;
  /**
   * Submission date for the revised version, used in the version strip.
   * When null/undefined the strip falls back to `comparison.created_at`.
   *
   * NOTE (M6-12): See `baseVersionSubmittedAt` — same placeholder rationale.
   */
  revisedVersionSubmittedAt?: string | null;
  /**
   * Word count for the base version, shown in the version strip.
   *
   * NOTE (M6-12): Per-version word counts are not included in the current
   * revision-comparison API response.  Defaults to 0 until a versions list
   * endpoint is available.
   */
  baseVersionWordCount?: number;
  /**
   * Word count for the revised version, shown in the version strip.
   *
   * NOTE (M6-12): See `baseVersionWordCount` — same placeholder rationale.
   */
  revisedVersionWordCount?: number;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * ResubmissionPanel — renders the full resubmission review interface.
 *
 * Displays:
 * 1. Version history strip (base vs. revised).
 * 2. Low-effort warning banner when flagged.
 * 3. Side-by-side content diff placeholder.
 * 4. Total score delta summary.
 * 5. Per-criterion score deltas with feedback-addressed indicators.
 */
export function ResubmissionPanel({
  comparison,
  criteria,
  baseVersionSubmittedAt,
  revisedVersionSubmittedAt,
  baseVersionWordCount = 0,
  revisedVersionWordCount = 0,
}: ResubmissionPanelProps) {
  // "active" version controls which version the user is comparing against.
  // "base" = original; "revised" = the resubmission.
  const [activeVersion, setActiveVersion] = useState<"base" | "revised">(
    "revised",
  );

  // Build a lookup map for criterion names.
  const criteriaMap = new Map(criteria.map((c) => [c.id, c]));

  // Build a lookup map for feedback-addressed items.
  const feedbackMap = new Map<string, FeedbackAddressedItemResponse>(
    (comparison.feedback_addressed ?? []).map((item) => [
      item.criterion_id,
      item,
    ]),
  );

  const fallbackDate = comparison.created_at;

  return (
    <div className="space-y-4">
      {/* ── Section heading ────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-900">
          Revision Comparison
        </h2>
        <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-700">
          Resubmitted
        </span>
      </div>

      {/* ── Version history strip ────────────────────────────────────── */}
      <div
        aria-label="Version history"
        className="flex gap-2"
      >
        <VersionButton
          label="Version 1 (Original)"
          submittedAt={baseVersionSubmittedAt ?? fallbackDate}
          wordCount={baseVersionWordCount}
          isActive={activeVersion === "base"}
          onClick={() => setActiveVersion("base")}
        />
        <VersionButton
          label="Version 2 (Revised)"
          submittedAt={revisedVersionSubmittedAt ?? fallbackDate}
          wordCount={revisedVersionWordCount}
          isActive={activeVersion === "revised"}
          onClick={() => setActiveVersion("revised")}
        />
      </div>

      {/* ── Low-effort warning ────────────────────────────────────────── */}
      {comparison.is_low_effort && (
        <LowEffortBanner reasons={comparison.low_effort_reasons} />
      )}

      {/* ── Side-by-side diff placeholder ────────────────────────────── */}
      <DiffPlaceholder activeVersion={activeVersion} />

      {/* ── Total score delta ─────────────────────────────────────────── */}
      <ScoreDeltaSummary delta={comparison.total_score_delta} />

      {/* ── Per-criterion deltas ──────────────────────────────────────── */}
      <section aria-labelledby="criterion-deltas-heading">
        <h3
          id="criterion-deltas-heading"
          className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500"
        >
          Criterion Score Changes
        </h3>
        {comparison.criterion_deltas.length === 0 ? (
          <p className="text-sm text-gray-400">No criterion data available.</p>
        ) : (
          <ul
            aria-label="Criterion score changes"
            className="space-y-2"
          >
            {comparison.criterion_deltas.map((delta) => {
              const criterion = criteriaMap.get(delta.criterion_id);
              const criterionName = criterion
                ? criterion.name
                : delta.criterion_id;
              const feedbackItem = feedbackMap.get(delta.criterion_id);

              return (
                <CriterionDeltaRow
                  key={delta.criterion_id}
                  delta={delta}
                  criterionName={criterionName}
                  feedbackItem={feedbackItem}
                />
              );
            })}
          </ul>
        )}
      </section>

      {/* ── Feedback-addressed legend ─────────────────────────────────── */}
      {comparison.feedback_addressed !== null && (
        <p className="text-xs text-gray-400">
          Feedback-addressed indicators are generated by AI and should be
          reviewed by the teacher. Expand each criterion to see the full
          assessment.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton — shown while the revision comparison is loading
// ---------------------------------------------------------------------------

/** Loading skeleton for the ResubmissionPanel. */
export function ResubmissionPanelSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      aria-label="Loading revision comparison"
      className="space-y-4"
    >
      {/* Heading */}
      <div className="h-5 w-40 animate-pulse rounded bg-gray-200" />
      {/* Version strip */}
      <div className="flex gap-2">
        <div className="h-16 flex-1 animate-pulse rounded-lg bg-gray-200" />
        <div className="h-16 flex-1 animate-pulse rounded-lg bg-gray-200" />
      </div>
      {/* Score delta */}
      <div className="h-12 animate-pulse rounded-lg bg-gray-200" />
      {/* Criterion rows */}
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-gray-200" />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state — shown when no revision comparison exists
// ---------------------------------------------------------------------------

/** Empty state shown when the essay has not been resubmitted yet. */
export function ResubmissionPanelEmpty() {
  return (
    <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
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
          d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
        />
      </svg>
      <p className="text-sm font-medium text-gray-500">No revision yet</p>
      <p className="mt-1 max-w-xs mx-auto text-xs text-gray-400">
        A revision comparison will appear here once the student has resubmitted
        and the revised essay has been graded.
      </p>
    </div>
  );
}
