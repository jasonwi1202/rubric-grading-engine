/**
 * Review queue sort/filter utilities — M3.22.
 *
 * Pure functions so they are trivially unit-testable without React or a DOM.
 * Imported by the ReviewQueue component and directly by unit tests.
 *
 * Security: operates only on already-provided teacher-facing review-list
 * fields (for example IDs, status values, scores, and `student_name` for
 * sorting) and never reads essay content.
 */

import type { ReviewQueueEssay } from "@/lib/api/essays";
import type { ConfidenceLevel } from "@/lib/api/grades";

// ---------------------------------------------------------------------------
// Derived status type for the review queue UI
// ---------------------------------------------------------------------------

/** Collapsed view status shown in the review queue. */
export type ReviewStatus = "unreviewed" | "in_review" | "locked" | "other";

/**
 * Map an essay's raw backend status to the three review-queue statuses shown
 * to teachers.
 *
 * Status mapping:
 *   graded    → unreviewed  (AI graded; teacher hasn't reviewed yet)
 *   reviewed  → in_review   (teacher has started reviewing but not locked)
 *   locked    → locked      (grade finalised)
 *   returned  → locked      (grade has been returned — treat as done)
 *   anything else → other   (uploading, queuing, grading — not in review phase)
 */
export function getReviewStatus(status: string): ReviewStatus {
  switch (status) {
    case "graded":
      return "unreviewed";
    case "reviewed":
      return "in_review";
    case "locked":
    case "returned":
      return "locked";
    default:
      return "other";
  }
}

// ---------------------------------------------------------------------------
// Filter
// ---------------------------------------------------------------------------

/** Which subset of essays to show in the queue. */
export type StatusFilter = "all" | "unreviewed" | "in_review" | "locked" | "low_confidence";

/**
 * Filter an essay list by review status.
 *
 * "all" passes every essay through without modification.
 * "low_confidence" includes only essays whose overall_confidence is "low".
 * Other values include only essays whose review status matches.
 */
export function filterEssays(
  essays: ReviewQueueEssay[],
  filter: StatusFilter,
): ReviewQueueEssay[] {
  if (filter === "all") return essays;
  if (filter === "low_confidence")
    return essays.filter((e) => e.overall_confidence === "low");
  return essays.filter((e) => getReviewStatus(e.status) === filter);
}

// ---------------------------------------------------------------------------
// Sort
// ---------------------------------------------------------------------------

/** Column the teacher has chosen to sort by. */
export type SortKey = "status" | "score" | "student_name" | "confidence";

/** Sort direction. */
export type SortDirection = "asc" | "desc";

/**
 * Numeric ordering for status sort. Lower index = shown first.
 * Unreviewed essays appear at the top (most in need of attention),
 * locked essays appear at the bottom (work is done).
 */
const STATUS_ORDER: Record<ReviewStatus, number> = {
  unreviewed: 0,
  in_review: 1,
  other: 2,
  locked: 3,
};

/**
 * Stable tie-breaker: sort by ISO 8601 submitted_at ascending (earlier first).
 * String comparison is correct for ISO dates without parsing overhead.
 */
function compareBySubmittedAt(a: ReviewQueueEssay, b: ReviewQueueEssay): number {
  return a.submitted_at < b.submitted_at ? -1 : a.submitted_at > b.submitted_at ? 1 : 0;
}

/**
 * Numeric ordering for confidence sort (low-confidence first in ascending order).
 * Essays with null/missing confidence are always placed last.
 */
const CONFIDENCE_ORDER: Record<ConfidenceLevel, number> = {
  low: 0,
  medium: 1,
  high: 2,
};

/**
 * Sort essays by the given key and direction. Returns a new array; the input
 * array is not mutated.
 *
 * Score sort: essays without a `total_score` (not yet graded) are always
 * placed last regardless of direction.
 *
 * Student name sort: case-insensitive. Essays with a null `student_name`
 * (unassigned) sort after named essays.
 *
 * Confidence sort: low-confidence first (ascending). Essays with a null or
 * missing `overall_confidence` are always placed last regardless of direction.
 */
export function sortEssays(
  essays: ReviewQueueEssay[],
  sortKey: SortKey,
  direction: SortDirection,
): ReviewQueueEssay[] {
  const multiplier = direction === "asc" ? 1 : -1;

  return [...essays].sort((a, b) => {
    switch (sortKey) {
      case "status": {
        const diff =
          STATUS_ORDER[getReviewStatus(a.status)] -
          STATUS_ORDER[getReviewStatus(b.status)];
        return diff * multiplier;
      }

      case "score": {
        // Null/undefined scores (essay not yet graded) always sorted last.
        // Non-finite parsed values (e.g. empty string) are also treated as missing.
        if (a.total_score == null && b.total_score == null) return 0;
        if (a.total_score == null) return 1;
        if (b.total_score == null) return -1;
        const aScore = parseFloat(a.total_score);
        const bScore = parseFloat(b.total_score);
        const aMissing = !Number.isFinite(aScore);
        const bMissing = !Number.isFinite(bScore);
        if (aMissing && bMissing) return 0;
        if (aMissing) return 1;
        if (bMissing) return -1;
        return (aScore - bScore) * multiplier;
      }

      case "student_name": {
        // Null / empty names (unassigned essays) always sorted last.
        if (!a.student_name && !b.student_name) return 0;
        if (!a.student_name) return 1;
        if (!b.student_name) return -1;
        const diff = a.student_name
          .toLowerCase()
          .localeCompare(b.student_name.toLowerCase());
        return diff * multiplier;
      }

      case "confidence": {
        // Null/missing confidence always sorted last regardless of direction.
        const aConf = a.overall_confidence ?? null;
        const bConf = b.overall_confidence ?? null;
        if (aConf === null && bConf === null) return compareBySubmittedAt(a, b);
        if (aConf === null) return 1;
        if (bConf === null) return -1;
        const aOrder = CONFIDENCE_ORDER[aConf];
        const bOrder = CONFIDENCE_ORDER[bConf];
        const diff = aOrder - bOrder;
        if (diff !== 0) return diff * multiplier;
        // Within the same confidence level: deterministic tie-break by submitted_at.
        return compareBySubmittedAt(a, b);
      }

      default:
        return 0;
    }
  });
}
