"use client";

/**
 * ReviewQueue — list view of all essays in an assignment for teacher triage.
 * M3.22 implementation.
 *
 * Features:
 * - Status badges: Unreviewed / In review / Locked
 * - Sort by: status (default), score (ascending/descending), student name
 * - Filter by status
 * - Keyboard navigation (ArrowUp / ArrowDown to move focus, Enter to open)
 * - Links to individual essay review interface (M3.21)
 *
 * Security:
 * - Essay IDs (UUIDs) are used in URLs, never student names.
 * - No essay content or student PII is logged or stored in browser storage.
 * - Student names are rendered in the teacher-only dashboard only.
 */

import { useState, useRef, useCallback, useId } from "react";
import Link from "next/link";
import type { ReviewQueueEssay } from "@/lib/api/essays";
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

const SORT_KEY_LABELS: Record<SortKey, string> = {
  status: "Status",
  score: "Score",
  student_name: "Student",
};

const FILTER_LABELS: Record<StatusFilter, string> = {
  all: "All",
  unreviewed: "Unreviewed",
  in_review: "In review",
  locked: "Locked",
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ReviewQueueProps {
  /** All essays for the assignment (fetched by the parent page). */
  essays: ReviewQueueEssay[];
  /** UUID of the assignment — used to build review links. */
  assignmentId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ReviewQueue({ essays, assignmentId }: ReviewQueueProps) {
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("status");
  const [sortDir, setSortDir] = useState<SortDirection>("asc");
  const [focusedIndex, setFocusedIndex] = useState<number>(-1);

  const rowRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const filterId = useId();

  // Derive the displayed list (filter then sort)
  const displayed = sortEssays(
    filterEssays(essays, filter),
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

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = Math.min(focusedIndex + 1, displayed.length - 1);
        setFocusedIndex(next);
        rowRefs.current[next]?.focus();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prev = Math.max(focusedIndex - 1, 0);
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
            value={filter}
            onChange={(e) => setFilter(e.target.value as StatusFilter)}
            className="rounded-md border border-gray-300 bg-white py-1.5 pl-2 pr-8 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {(
              ["all", "unreviewed", "in_review", "locked"] as StatusFilter[]
            ).map((f) => (
              <option key={f} value={f}>
                {FILTER_LABELS[f]}
              </option>
            ))}
          </select>
        </div>

        {/* Sort buttons */}
        <div
          className="flex items-center gap-1"
          role="group"
          aria-label="Sort essays by"
        >
          <span className="text-sm font-medium text-gray-700">Sort:</span>
          {(["status", "score", "student_name"] as SortKey[]).map((key) => (
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
            const scoreLabel =
              essay.total_score != null && essay.max_possible_score != null
                ? `${parseFloat(essay.total_score)} / ${parseFloat(essay.max_possible_score)}`
                : null;

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
                aria-label={`Review essay${essay.student_name ? ` for student ${essay.student_name}` : ""} — status: ${REVIEW_STATUS_LABELS[reviewStatus]}${scoreLabel ? `, score: ${scoreLabel}` : ""}`}
              >
                {/* Status badge */}
                <span
                  className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${REVIEW_STATUS_COLORS[reviewStatus]}`}
                  aria-hidden="true"
                >
                  {REVIEW_STATUS_LABELS[reviewStatus]}
                </span>

                {/* Student label — shows UUID fragment when unassigned to avoid "no name" confusion */}
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
