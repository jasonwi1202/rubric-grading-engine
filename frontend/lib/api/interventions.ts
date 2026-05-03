/**
 * Intervention recommendations API helpers — M7-01 / M8-01.
 *
 * Covers:
 *   GET    /interventions             — list recommendations (pending by default)
 *   POST   /interventions/{id}/approve — teacher approves a recommendation
 *   DELETE /interventions/{id}         — teacher dismisses a recommendation
 *
 * Aligned with backend `app/schemas/intervention.py` response shapes.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 * - No student data is stored in localStorage / sessionStorage.
 */

import { apiDelete, apiGet, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Trigger type that generated this intervention recommendation. */
export type InterventionTriggerType =
  | "regression"
  | "non_responder"
  | "persistent_gap"
  | "high_inconsistency"
  | "trajectory_risk";

/** Lifecycle status of an intervention recommendation. */
export type InterventionStatus = "pending_review" | "approved" | "dismissed";

/** A single intervention recommendation. Matches backend InterventionRecommendationResponse. */
export interface InterventionRecommendation {
  id: string;
  teacher_id: string;
  student_id: string;
  trigger_type: InterventionTriggerType;
  /** Canonical skill dimension key, or null for student-level triggers. */
  skill_key: string | null;
  /** Urgency score 1–4; 4 = most urgent. */
  urgency: number;
  trigger_reason: string;
  evidence_summary: string;
  suggested_action: string;
  details: Record<string, unknown>;
  status: InterventionStatus;
  actioned_at: string | null;
  created_at: string;
}

/** List response for interventions. Matches backend InterventionListResponse. */
export interface InterventionListResponse {
  teacher_id: string;
  items: InterventionRecommendation[];
  total_count: number;
}

/** Status filter values accepted by GET /interventions. */
export type InterventionStatusFilter =
  | "pending_review"
  | "approved"
  | "dismissed"
  | "all";

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch the authenticated teacher's intervention recommendations.
 * Calls GET /interventions?status=<filter>.
 * Defaults to 'pending_review' when status is omitted.
 */
export async function listInterventions(
  status?: InterventionStatusFilter,
): Promise<InterventionListResponse> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiGet<InterventionListResponse>(`/interventions${qs}`);
}

/**
 * Approve an intervention recommendation (teacher-confirmed action).
 * Calls POST /interventions/{id}/approve.
 * Idempotent — approving an already-approved item returns 200 unchanged.
 */
export async function approveIntervention(
  id: string,
): Promise<InterventionRecommendation> {
  return apiPost<InterventionRecommendation>(`/interventions/${id}/approve`, {});
}

/**
 * Dismiss an intervention recommendation permanently.
 * Calls DELETE /interventions/{id}.
 * Idempotent — dismissing an already-dismissed item returns 200 unchanged.
 */
export async function dismissIntervention(
  id: string,
): Promise<InterventionRecommendation> {
  return apiDelete<InterventionRecommendation>(`/interventions/${id}`);
}
