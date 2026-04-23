/**
 * Grades API helpers — M3.21 (Essay review interface).
 *
 * Covers:
 *   GET   /essays/{essayId}/grade                      — fetch current grade
 *   PATCH /grades/{gradeId}/feedback                   — edit summary feedback
 *   PATCH /grades/{gradeId}/criteria/{criterionScoreId} — override score or feedback
 *   POST  /grades/{gradeId}/lock                       — lock grade as final
 *
 * Aligned with backend `app/schemas/grade.py` response shapes.
 * Note: `PatchCriterionRequest` intentionally restricts fields to non-null
 * values to match the current backend validator contract.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 * - Essay content is never stored client-side (no localStorage/sessionStorage).
 */

import { apiGet, apiPatch, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** LLM confidence in a criterion score. */
export type ConfidenceLevel = "high" | "medium" | "low";

/** Grading strictness applied at grade-generation time. */
export type StrictnessLevel = "lenient" | "balanced" | "strict";

/**
 * Per-criterion score within a GradeResponse.
 * Matches backend `CriterionScoreResponse` exactly.
 *
 * `rubric_criterion_id` cross-references the criterion in
 * `assignment.rubric_snapshot.criteria[].id` so callers can look up
 * the criterion name, weight, and score range.
 */
export interface CriterionScoreResponse {
  /** UUID of the CriterionScore row. */
  id: string;
  /** UUID of the rubric criterion — used to look up name/weight in the snapshot. */
  rubric_criterion_id: string;
  ai_score: number;
  /** Teacher override — null when no override has been made. */
  teacher_score: number | null;
  /** final_score = teacher_score ?? ai_score */
  final_score: number;
  ai_justification: string;
  /** AI-generated per-criterion student feedback; null for older grades. */
  ai_feedback: string | null;
  /** Teacher-written criterion feedback; null until the teacher edits it. */
  teacher_feedback: string | null;
  confidence: ConfidenceLevel;
  created_at: string;
}

/**
 * Full grade response returned by GET /essays/{essayId}/grade.
 * Matches backend `GradeResponse` exactly.
 */
export interface GradeResponse {
  id: string;
  essay_version_id: string;
  /** Sum of all criterion final_scores. Recalculated after every override.
   *  Serialized as a JSON string from backend Decimal (e.g. "7.00"). */
  total_score: string;
  /** Sum of all criterion max_scores — fixed at grade creation time.
   *  Serialized as a JSON string from backend Decimal (e.g. "10.00"). */
  max_possible_score: string;
  /** AI-generated overall summary feedback. */
  summary_feedback: string;
  /** Teacher-edited summary feedback; null until the teacher edits it. */
  summary_feedback_edited: string | null;
  strictness: StrictnessLevel;
  ai_model: string;
  prompt_version: string;
  is_locked: boolean;
  locked_at: string | null;
  /** Derived from criterion confidence levels: low if any criterion is low;
   *  medium if any is medium (and none is low); high if all are high.
   *  Null for grades written before M4.1. */
  overall_confidence: ConfidenceLevel | null;
  created_at: string;
  criterion_scores: CriterionScoreResponse[];
}

/**
 * Request body for PATCH /grades/{gradeId}/criteria/{criterionScoreId}.
 * At least one field must be provided (validated by backend).
 *
 * Note: the backend validator 422s when both fields are None; sending an
 * explicit JSON `null` maps to None and triggers the same error. Clearing
 * a criterion override/feedback is not supported by the current backend
 * contract — omit the field to leave it unchanged.
 *
 * Matches backend `PatchCriterionRequest`.
 */
export interface PatchCriterionRequest {
  teacher_score?: number;
  teacher_feedback?: string;
}

/**
 * Request body for PATCH /grades/{gradeId}/feedback.
 * Matches backend `PatchFeedbackRequest`.
 */
export interface PatchFeedbackRequest {
  /** min_length: 1, max_length: 10000 (server-enforced). */
  summary_feedback: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch the current grade for an essay, including all criterion scores.
 * Calls GET /api/v1/essays/{essayId}/grade.
 */
export async function getGrade(essayId: string): Promise<GradeResponse> {
  return apiGet<GradeResponse>(`/essays/${essayId}/grade`);
}

/**
 * Override a criterion score and/or feedback for a grade.
 * Calls PATCH /api/v1/grades/{gradeId}/criteria/{criterionScoreId}.
 *
 * Returns the full updated GradeResponse (including recalculated total_score).
 */
export async function overrideCriterionScore(
  gradeId: string,
  criterionScoreId: string,
  data: PatchCriterionRequest,
): Promise<GradeResponse> {
  return apiPatch<GradeResponse>(
    `/grades/${gradeId}/criteria/${criterionScoreId}`,
    data,
  );
}

/**
 * Update the teacher-edited summary feedback for a grade.
 * Calls PATCH /api/v1/grades/{gradeId}/feedback.
 */
export async function updateFeedback(
  gradeId: string,
  data: PatchFeedbackRequest,
): Promise<GradeResponse> {
  return apiPatch<GradeResponse>(`/grades/${gradeId}/feedback`, data);
}

/**
 * Lock a grade as final. No further edits are allowed after locking.
 * Calls POST /api/v1/grades/{gradeId}/lock.
 *
 * Idempotent — locking an already-locked grade succeeds without error.
 */
export async function lockGrade(gradeId: string): Promise<GradeResponse> {
  return apiPost<GradeResponse>(`/grades/${gradeId}/lock`, {});
}
