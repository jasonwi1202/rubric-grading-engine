/**
 * Regrade requests API helpers — M4.9 implementation.
 *
 * Covers:
 *   POST  /grades/{gradeId}/regrade-requests               — submit a request
 *   GET   /assignments/{assignmentId}/regrade-requests      — list for assignment
 *   POST  /regrade-requests/{requestId}/resolve             — approve or deny
 *   POST  /assignments/{assignmentId}/close-regrade-window  — close the window
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 * - dispute_text and resolution_note may contain PII — never log their contents.
 */

import { apiGet, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Lifecycle status of a regrade request. Matches backend RegradeRequestStatus. */
export type RegradeRequestStatus = "open" | "approved" | "denied";

/**
 * A regrade request returned by the API.
 * Matches backend `RegradeRequestResponse` exactly.
 *
 * `criterion_score_id` is null when the request targets the overall grade
 * rather than a specific criterion.
 */
export interface RegradeRequest {
  id: string;
  grade_id: string;
  /** UUID of the CriterionScore being disputed, or null for overall grade. */
  criterion_score_id: string | null;
  teacher_id: string;
  /** Teacher-entered justification — may contain student PII; never log. */
  dispute_text: string;
  status: RegradeRequestStatus;
  /** Written explanation of the decision — may contain PII; never log. */
  resolution_note: string | null;
  resolved_at: string | null;
  created_at: string;
}

/**
 * Request body for POST /grades/{gradeId}/regrade-requests.
 * Matches backend `RegradeRequestCreate`.
 */
export interface RegradeRequestCreate {
  /** min_length: 1, max_length: 5000 (server-enforced); UI enforces max 500. */
  dispute_text: string;
  /** UUID of CriterionScore to dispute, or null/undefined for overall grade. */
  criterion_score_id?: string | null;
}

/**
 * Request body for POST /regrade-requests/{requestId}/resolve.
 * Matches backend `RegradeRequestResolveRequest`.
 */
export interface RegradeRequestResolveRequest {
  resolution: "approved" | "denied";
  /** Required when resolution is 'denied'. */
  resolution_note?: string | null;
  /** New teacher score when approving a criterion-level request. */
  new_criterion_score?: number | null;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Submit a regrade request for a grade.
 * Calls POST /api/v1/grades/{gradeId}/regrade-requests.
 *
 * Returns 409 if the submission window is closed or the request limit is reached.
 */
export async function createRegradeRequest(
  gradeId: string,
  body: RegradeRequestCreate,
): Promise<RegradeRequest> {
  return apiPost<RegradeRequest>(`/grades/${gradeId}/regrade-requests`, body);
}

/**
 * List all regrade requests for an assignment, ordered oldest-first.
 * Calls GET /api/v1/assignments/{assignmentId}/regrade-requests.
 */
export async function listRegradeRequests(
  assignmentId: string,
): Promise<RegradeRequest[]> {
  return apiGet<RegradeRequest[]>(
    `/assignments/${assignmentId}/regrade-requests`,
  );
}

/**
 * Approve or deny a regrade request.
 * Calls POST /api/v1/regrade-requests/{requestId}/resolve.
 *
 * - Approval: `new_criterion_score` optionally overrides the criterion score.
 * - Denial: `resolution_note` is required (enforced by backend).
 */
export async function resolveRegradeRequest(
  requestId: string,
  body: RegradeRequestResolveRequest,
): Promise<RegradeRequest> {
  return apiPost<RegradeRequest>(
    `/regrade-requests/${requestId}/resolve`,
    body,
  );
}

/**
 * Close the regrade submission window for an assignment.
 * Calls POST /api/v1/assignments/{assignmentId}/close-regrade-window.
 *
 * After this call, no new regrade requests can be submitted for the assignment.
 */
export async function closeRegradeWindow(
  assignmentId: string,
): Promise<void> {
  return apiPost<void>(
    `/assignments/${assignmentId}/close-regrade-window`,
    {},
  );
}
