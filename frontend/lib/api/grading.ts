/**
 * Grading API helpers — M3.17 (Batch grading UI).
 *
 * Covers batch grading trigger, status polling, and per-essay retry.
 *
 * Status state machine (server-enforced):
 *   POST /assignments/{id}/grade            → 202 Accepted, assignment → grading
 *   GET  /assignments/{id}/grading-status   → progress snapshot from Redis
 *   POST /essays/{id}/grade/retry           → re-enqueues a failed essay
 *
 * Security notes:
 * - No essay content or student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 */

import { apiGet, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Strictness level passed to the grading LLM. */
export type GradingStrictness = "lenient" | "balanced" | "strict";

/** Request body for POST /assignments/{id}/grade. */
export interface TriggerGradingRequest {
  /** Omit to grade all queued essays. */
  essay_ids?: string[];
  strictness?: GradingStrictness;
}

/** Overall batch progress status. */
export type GradingBatchStatus =
  | "idle"
  | "processing"
  | "complete"
  | "failed"
  | "partial";

/**
 * Per-essay status entry returned by the grading-status endpoint.
 * Matches backend `EssayProgressItem.status` values.
 */
export type EssayGradingStatus =
  | "queued"
  | "grading"
  | "complete"
  | "failed";

/**
 * One essay entry within a grading-status response.
 * Matches backend `EssayProgressItem` schema exactly.
 */
export interface EssayGradingEntry {
  /** UUID of the essay. */
  id: string;
  status: EssayGradingStatus;
  /**
   * Student display name — `null` when the essay is not yet assigned.
   * Teacher-facing only; never included in logs.
   */
  student_name: string | null;
  /**
   * Error type code (e.g. "LLM_TIMEOUT", "PARSE_ERROR").
   * Always present in the response; `null` when the error type is unknown.
   * Never contains raw exception messages or student essay content.
   */
  error: string | null;
}

/**
 * Response from GET /assignments/{id}/grading-status.
 * Matches backend `GradingStatusResponse` schema exactly.
 */
export interface GradingStatusResponse {
  status: GradingBatchStatus;
  total: number;
  complete: number;
  failed: number;
  essays: EssayGradingEntry[];
}

/**
 * Response from POST /assignments/{id}/grade (202 Accepted body).
 * Matches backend `TriggerGradingResponse` schema.
 */
export interface TriggerGradingResponse {
  enqueued: number;
  assignment_id: string;
}

/** Response from POST /essays/{essayId}/grade/retry. */
export interface RetryGradingResponse {
  message: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Trigger batch grading for an assignment.
 * Calls POST /api/v1/assignments/{assignmentId}/grade.
 * Returns 202 — grading happens asynchronously via Celery.
 */
export async function triggerGrading(
  assignmentId: string,
  data: TriggerGradingRequest = {},
): Promise<TriggerGradingResponse> {
  return apiPost<TriggerGradingResponse>(
    `/assignments/${assignmentId}/grade`,
    data,
  );
}

/**
 * Poll the batch grading progress for an assignment.
 * Calls GET /api/v1/assignments/{assignmentId}/grading-status.
 */
export async function getGradingStatus(
  assignmentId: string,
): Promise<GradingStatusResponse> {
  return apiGet<GradingStatusResponse>(
    `/assignments/${assignmentId}/grading-status`,
  );
}

/**
 * Re-enqueue a single failed essay for grading.
 * Calls POST /api/v1/essays/{essayId}/grade/retry.
 */
export async function retryEssayGrading(
  essayId: string,
): Promise<RetryGradingResponse> {
  return apiPost<RetryGradingResponse>(`/essays/${essayId}/grade/retry`, {});
}
