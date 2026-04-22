/**
 * Review queue sort/filter utilities — M3.22.
 *
 * Pure functions so they are trivially unit-testable without React or a DOM.
 * Imported by the ReviewQueue component and directly by unit tests.
 *
 * Security: operates on entity IDs and status strings only — never on
 * essay content or student PII beyond what is already present in the
 * teacher-facing review list.
 */

import type { ReviewQueueEssay } from "@/lib/api/essays";

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
export type StatusFilter = "all" | "unreviewed" | "in_review" | "locked";

/**
 * Filter an essay list by review status.
 *
 * "all" passes every essay through without modification.
 * Other values include only essays whose review status matches.
 */
export function filterEssays(
  essays: ReviewQueueEssay[],
  filter: StatusFilter,
): ReviewQueueEssay[] {
  if (filter === "all") return essays;
  return essays.filter((e) => getReviewStatus(e.status) === filter);
}

// ---------------------------------------------------------------------------
// Sort
// ---------------------------------------------------------------------------

/** Column the teacher has chosen to sort by. */
export type SortKey = "status" | "score" | "student_name";

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
 * Sort essays by the given key and direction. Returns a new array; the input
 * array is not mutated.
 *
 * Score sort: essays without a `total_score` (not yet graded) are always
 * placed last regardless of direction.
 *
 * Student name sort: case-insensitive. Essays with a null `student_name`
 * (unassigned) sort after named essays.
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
        // Null scores (essay not yet graded) always sorted last.
        if (a.total_score === null && b.total_score === null) return 0;
        if (a.total_score === null) return 1;
        if (b.total_score === null) return -1;
        const diff = parseFloat(a.total_score) - parseFloat(b.total_score);
        return diff * multiplier;
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

      default:
        return 0;
    }
  });
}
