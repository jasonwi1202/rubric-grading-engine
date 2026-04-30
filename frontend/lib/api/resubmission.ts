/**
 * Resubmission API helpers — M6-12 (Resubmission UI).
 *
 * Covers:
 *   GET /essays/{essayId}/revision-comparison — fetch the revision comparison
 *       for a resubmitted essay.
 *
 * Aligned with backend `app/schemas/essay.py` response shapes:
 *   RevisionComparisonResponse, CriterionDeltaResponse,
 *   FeedbackAddressedItemResponse.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 */

import { apiGet } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Score delta for a single rubric criterion between two essay versions.
 * Matches backend `CriterionDeltaResponse` exactly.
 */
export interface CriterionDeltaResponse {
  criterion_id: string;
  base_score: number;
  revised_score: number;
  /** revised_score − base_score; negative means regression. */
  delta: number;
}

/**
 * LLM assessment of whether a single criterion's feedback was addressed.
 * Matches backend `FeedbackAddressedItemResponse` exactly.
 */
export interface FeedbackAddressedItemResponse {
  criterion_id: string;
  /** The feedback text that was given on the base submission. */
  feedback_given: string;
  /** True when the LLM determined the feedback was addressed in the revision. */
  addressed: boolean;
  /** Human-readable LLM explanation of the assessment. */
  detail: string;
}

/**
 * Full revision comparison returned by
 * GET /essays/{essayId}/revision-comparison.
 * Matches backend `RevisionComparisonResponse` exactly.
 *
 * `feedback_addressed` is `null` when the LLM analysis was skipped (no
 * criterion feedback existed on the base submission) or failed.  Callers
 * must treat `null` as "not available" and hide that section.
 */
export interface RevisionComparisonResponse {
  id: string;
  essay_id: string;
  base_version_id: string;
  revised_version_id: string;
  base_grade_id: string;
  revised_grade_id: string;
  /** Revised total score minus base total score.  Positive = improvement. */
  total_score_delta: number;
  criterion_deltas: CriterionDeltaResponse[];
  /** True when heuristics detect a surface-level (low-effort) revision. */
  is_low_effort: boolean;
  low_effort_reasons: string[];
  /** Per-criterion feedback-addressed assessment; null when unavailable. */
  feedback_addressed: FeedbackAddressedItemResponse[] | null;
  /** ISO-8601 datetime when this comparison was created. */
  created_at: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch the revision comparison for a resubmitted essay.
 * Calls GET /api/v1/essays/{essayId}/revision-comparison.
 *
 * Returns 404 when the essay has not been resubmitted and re-graded yet.
 * Callers should catch ApiError(404) and treat it as "no comparison available".
 *
 * Security: no student PII is logged — only entity IDs appear in any log path.
 */
export async function getRevisionComparison(
  essayId: string,
): Promise<RevisionComparisonResponse> {
  return apiGet<RevisionComparisonResponse>(
    `/essays/${essayId}/revision-comparison`,
  );
}
