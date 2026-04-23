"use client";

/**
 * ReviewQueue — list view of all essays in an assignment for teacher triage.
 * M3.22 implementation; extended in M4.2 with confidence-based triage.
 *
 * Features:
 * - Status badges: Unreviewed / In review / Locked
 * - Confidence badges: high / medium / low (M4.2)
 * - Sort by: confidence (default, low first), status, score, student name
 * - Filter by status; fast-review mode filters to low-confidence only (M4.2)
 * - Bulk-approve: lock all high-confidence, non-locked essays at once (M4.2)
 * - Keyboard navigation (ArrowUp / ArrowDown to move focus, Enter to open)
 * - Links to individual essay review interface (M3.21)
 *
 * Security:
 * - Essay IDs (UUIDs) are used in URLs, never student names.
 * - No essay content or student PII is logged or stored in browser storage.
 * - Student names are rendered in the teacher-only dashboard only.
 */

import { useState, useRef, useCallback, useId, useMemo } from "react";
import Link from "next/link";
import type { ReviewQueueEssay } from "@/lib/api/essays";
import { lockGrade } from "@/lib/api/grades";
import {
  filterEssays,
  sortEssays,
  getReviewStatus,
  type StatusFilter,
  type SortKey,
  type SortDirection,
  type ReviewStatus,
} from "@/lib/utils/reviewQueue";

// ---------------------------------------------------------------------------
// Badge helpers
// ---------------------------------------------------------------------------

const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  unreviewed: "Unreviewed",
  in_review: "In review",
  locked: "Locked",
  other: "Pending",
};

const REVIEW_STATUS_COLORS: Record<ReviewStatus, string> = {
  unreviewed: "bg-blue-100 text-blue-700",
  in_review: "bg-yellow-100 text-yellow-700",
  locked: "bg-green-100 text-green-700",
  other: "bg-gray-100 text-gray-600",
};

const CONFIDENCE_BADGE_LABELS: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

const CONFIDENCE_BADGE_COLORS: Record<string, string> = {
  high: "bg-green-100 text-green-700",
  medium: "bg-yellow-100 text-yellow-700",
  low: "bg-red-100 text-red-700",
};

const SORT_KEY_LABELS: Record<SortKey, string> = {
  confidence: "Confidence",
  status: "Status",
  score: "Score",
  student_name: "Student",
};

const FILTER_LABELS: Record<StatusFilter, string> = {
  all: "All",
  unreviewed: "Unreviewed",
  in_review: "In review",
  locked: "Locked",
  low_confidence: "Low confidence",
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ReviewQueueProps {
  /** All essays for the assignment (fetched by the parent page). */
  essays: ReviewQueueEssay[];
  /** UUID of the assignment — used to build review links. */
  assignmentId: string;
  /**
   * Called after bulk-approve successfully locks high-confidence essays.
   * The parent should invalidate its essay list query to reflect updated status.
   */
  onBulkApproveSuccess?: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ReviewQueue({ essays, assignmentId, onBulkApproveSuccess }: ReviewQueueProps) {
  const [filter, setFilter] = useState<StatusFilter>("all");
  // Default sort: confidence ascending (low-confidence first) — M4.2
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [sortDir, setSortDir] = useState<SortDirection>("asc");
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);
  // Fast-review mode: show only low-confidence essays — M4.2
  const [fastReview, setFastReview] = useState<boolean>(false);

  // Bulk-approve state — M4.2
  const [bulkApproving, setBulkApproving] = useState(false);
  const [bulkApproveError, setBulkApproveError] = useState<string | null>(null);

  const rowRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const filterId = useId();
  const fastReviewId = useId();

  // High-confidence essays that are not yet locked and have a grade_id.
  // These are candidates for bulk-approve.
  const highConfidenceUnlocked = useMemo(
    () =>
      essays.filter(
        (e) =>
          e.overall_confidence === "high" &&
          getReviewStatus(e.status) !== "locked" &&
          e.grade_id != null,
      ),
    [essays],
  );

  // Derive the displayed list: apply fast-review override then status filter, then sort.
  const activeFilter: StatusFilter = fastReview ? "low_confidence" : filter;
  const displayed = sortEssays(
    filterEssays(essays, activeFilter),
    sortKey,
    sortDir,
  );

  // Update refs array length to match displayed list
  rowRefs.current = rowRefs.current.slice(0, displayed.length);

  const handleSortChange = useCallback(
    (key: SortKey) => {
      if (key === sortKey) {
        // Toggle direction when clicking the same column
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir("asc");
      }
    },
    [sortKey],
  );

  /** Keyboard navigation handler — ArrowUp/Down/Enter on the list container. */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (displayed.length === 0) return;

      // Clamp the stored index in case the list shrank after a filter change.
      // `displayed.length > 0` is guaranteed by the guard above.
      const current = Math.max(0, Math.min(focusedIndex, displayed.length - 1));

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = Math.min(current + 1, displayed.length - 1);
        setFocusedIndex(next);
        rowRefs.current[next]?.focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prev = Math.max(current - 1, 0);
        setFocusedIndex(prev);
        rowRefs.current[prev]?.focus();
      }
      // Enter is handled natively by the <a> element when focused.
    },
    [displayed.length, focusedIndex],
  );

  const sortIndicator = (key: SortKey) => {
    if (sortKey !== key) return null;
    return (
      <span aria-hidden="true" className="ml-1 select-none">
        {sortDir === "asc" ? "↑" : "↓"}
      </span>
    );
  };

  /** Bulk-approve: lock all high-confidence, non-locked essays. */
  const handleBulkApprove = useCallback(async () => {
    if (highConfidenceUnlocked.length === 0) return;
    setBulkApproving(true);
    setBulkApproveError(null);
    try {
      await Promise.all(
        highConfidenceUnlocked.map((e) => lockGrade(e.grade_id!)),
      );
      onBulkApproveSuccess?.();
    } catch {
      setBulkApproveError(
        "Failed to approve some essays. Please refresh and try again.",
      );
    } finally {
      setBulkApproving(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [essays, onBulkApproveSuccess]);

  return (
    <div>
      {/* Controls row */}
      <div className="mb-4 flex flex-wrap items-center gap-4">
        {/* Filter */}
        <div className="flex items-center gap-2">
          <label
            htmlFor={filterId}
            className="text-sm font-medium text-gray-700"
          >
            Filter:
          </label>
          <select
            id={filterId}
            value={fastReview ? "low_confidence" : filter}
            onChange={(e) => {
              const val = e.target.value as StatusFilter;
              if (val === "low_confidence") {
                setFastReview(true);
              } else {
                setFastReview(false);
                setFilter(val);
              }
            }}
            className="rounded-md border border-gray-300 bg-white py-1.5 pl-2 pr-8 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {(
              ["all", "unreviewed", "in_review", "locked", "low_confidence"] as StatusFilter[]
            ).map((f) => (
              <option key={f} value={f}>
                {FILTER_LABELS[f]}
              </option>
            ))}
          </select>
        </div>

        {/* Fast-review mode toggle — M4.2 */}
        <div className="flex items-center gap-2">
          <input
            id={fastReviewId}
            type="checkbox"
            checked={fastReview}
            onChange={(e) => setFastReview(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <label htmlFor={fastReviewId} className="text-sm font-medium text-gray-700">
            Fast review
          </label>
        </div>

        {/* Sort buttons */}
        <div
          className="flex items-center gap-1"
          role="group"
          aria-label="Sort essays by"
        >
          <span className="text-sm font-medium text-gray-700">Sort:</span>
          {(["confidence", "status", "score", "student_name"] as SortKey[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => handleSortChange(key)}
              aria-pressed={sortKey === key}
              className={`rounded-md px-3 py-1.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 ${
                sortKey === key
                  ? "bg-blue-600 text-white shadow-sm"
                  : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
              }`}
            >
              {SORT_KEY_LABELS[key]}
              {sortIndicator(key)}
            </button>
          ))}
        </div>

        {/* Count */}
        <span className="ml-auto text-sm text-gray-500" aria-live="polite">
          {displayed.length} of {essays.length} essay
          {essays.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Bulk-approve — M4.2 */}
      {highConfidenceUnlocked.length > 0 && (
        <div className="mb-4">
          {bulkApproveError && (
            <p role="alert" className="mb-2 text-sm text-red-700">
              {bulkApproveError}
            </p>
          )}
          <button
            type="button"
            onClick={handleBulkApprove}
            disabled={bulkApproving}
            aria-label={
              bulkApproving
                ? `Approving ${highConfidenceUnlocked.length} high-confidence essay${highConfidenceUnlocked.length !== 1 ? "s" : ""}…`
                : `Bulk approve and lock ${highConfidenceUnlocked.length} high-confidence essay${highConfidenceUnlocked.length !== 1 ? "s" : ""}`
            }
            className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {bulkApproving
              ? "Approving…"
              : `Approve ${highConfidenceUnlocked.length} high-confidence essay${highConfidenceUnlocked.length !== 1 ? "s" : ""}`}
          </button>
        </div>
      )}

      {/* Empty state */}
      {displayed.length === 0 && (
        <div className="rounded-lg border-2 border-dashed border-gray-200 p-10 text-center">
          <p className="text-sm text-gray-500">
            {essays.length === 0
              ? "No essays have been submitted yet."
              : "No essays match the selected filter."}
          </p>
        </div>
      )}

      {/* Essay list — keyboard nav container */}
      {displayed.length > 0 && (
        <div
          role="list"
          aria-label="Essays in this assignment"
          onKeyDown={handleKeyDown}
        >
          {displayed.map((essay, idx) => {
            const reviewStatus = getReviewStatus(essay.status);
            const scoreLabel = (() => {
              if (
                essay.total_score == null ||
                essay.max_possible_score == null
              ) {
                return null;
              }
              const totalScore = parseFloat(essay.total_score);
              const maxPossibleScore = parseFloat(essay.max_possible_score);
              if (
                !Number.isFinite(totalScore) ||
                !Number.isFinite(maxPossibleScore)
              ) {
                return null;
              }
              return `${totalScore} / ${maxPossibleScore}`;
            })();

            const confidenceLevel = essay.overall_confidence ?? null;

            return (
              <Link
                key={essay.essay_id}
                href={`/dashboard/assignments/${assignmentId}/review/${essay.essay_id}`}
                role="listitem"
                ref={(el) => {
                  rowRefs.current[idx] = el;
                }}
                onFocus={() => setFocusedIndex(idx)}
                className="mb-2 flex items-center gap-4 rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm transition-colors hover:border-blue-300 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
                aria-label={`Review essay${essay.student_name ? ` for student ${essay.student_name}` : ""} — status: ${REVIEW_STATUS_LABELS[reviewStatus]}${confidenceLevel ? `, confidence: ${confidenceLevel}` : ""}${scoreLabel ? `, score: ${scoreLabel}` : ""}`}
              >
                {/* Status badge */}
                <span
                  className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${REVIEW_STATUS_COLORS[reviewStatus]}`}
                  aria-hidden="true"
                >
                  {REVIEW_STATUS_LABELS[reviewStatus]}
                </span>

                {/* Confidence badge — M4.2 */}
                {confidenceLevel != null ? (
                  <span
                    className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      CONFIDENCE_BADGE_COLORS[confidenceLevel] ??
                      "bg-gray-100 text-gray-600"
                    }`}
                    aria-label={`Confidence: ${confidenceLevel}`}
                  >
                    {CONFIDENCE_BADGE_LABELS[confidenceLevel] ?? confidenceLevel}
                  </span>
                ) : null}

                {/* Student label — shows the student name, or "Unassigned" when no student is assigned */}
                <span className="flex-1 truncate text-sm font-medium text-gray-900">
                  {essay.student_name ?? (
                    <span className="italic text-gray-400">Unassigned</span>
                  )}
                </span>

                {/* Score */}
                <span className="shrink-0 text-sm text-gray-500">
                  {scoreLabel ?? <span className="italic">—</span>}
                </span>

                {/* Chevron */}
                <svg
                  aria-hidden="true"
                  className="h-4 w-4 shrink-0 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              </Link>
            );
          })}
        </div>
      )}

      {/* Keyboard hint */}
      {displayed.length > 1 && (
        <p className="mt-3 text-xs text-gray-400">
          Tip: Use{" "}
          <kbd className="rounded border border-gray-300 px-1 py-0.5 font-mono text-xs">
            ↑
          </kbd>{" "}
          /{" "}
          <kbd className="rounded border border-gray-300 px-1 py-0.5 font-mono text-xs">
            ↓
          </kbd>{" "}
          arrow keys to move between essays, then{" "}
          <kbd className="rounded border border-gray-300 px-1 py-0.5 font-mono text-xs">
            Enter
          </kbd>{" "}
          to open.
        </p>
      )}
    </div>
  );
}
