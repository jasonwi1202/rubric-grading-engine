/**
 * Integrity report API helpers — M4.6 implementation.
 *
 * Covers:
 *   GET   /essays/{essayId}/integrity                   — fetch latest integrity report
 *   GET   /assignments/{assignmentId}/integrity/summary — class-level counts
 *   PATCH /integrity-reports/{reportId}/status          — update teacher review status
 *
 * All language is framed as signals, not findings (e.g. "potential similarity
 * detected") — this is enforced in the UI layer, not here.
 *
 * Security notes:
 * - No essay content or student PII is logged; only entity IDs are used.
 * - All endpoints require a valid JWT access token.
 * - Integrity signals are read-only in terms of content; only the review
 *   status (teacher action) is mutable from the frontend.
 */

import { apiGet, apiPatch } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Teacher review status for an integrity report. */
export type IntegrityReportStatus = "pending" | "reviewed_clear" | "flagged";

/**
 * One flagged passage excerpt from an integrity check.
 * Provider-specific — fields may be absent depending on the provider.
 */
export interface FlaggedPassage {
  text: string;
  ai_probability?: number | null;
  start_char?: number | null;
  end_char?: number | null;
  signal_type?: string | null;
  source?: string | null;
}

/**
 * Full integrity report response returned by GET /essays/{essayId}/integrity.
 * Matches backend `IntegrityReportResponse` exactly.
 */
export interface IntegrityReportResponse {
  id: string;
  essay_version_id: string;
  provider: string;
  /** Probability [0.0, 1.0] that the text is AI-generated; null if not available. */
  ai_likelihood: number | null;
  /** Overall similarity score [0.0, 1.0]; null if not available. */
  similarity_score: number | null;
  /** Zero or more flagged passage excerpts. */
  flagged_passages: FlaggedPassage[];
  status: IntegrityReportStatus;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Request body for PATCH /integrity-reports/{reportId}/status.
 * Only "reviewed_clear" and "flagged" are valid teacher-action values.
 */
export interface PatchIntegrityStatusRequest {
  status: "reviewed_clear" | "flagged";
}

/**
 * Aggregate integrity signal counts for an assignment.
 * Matches backend `IntegritySummaryResponse`.
 */
export interface IntegritySummaryResponse {
  assignment_id: string;
  flagged: number;
  reviewed_clear: number;
  pending: number;
  total: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch the latest integrity report for an essay.
 * Calls GET /api/v1/essays/{essayId}/integrity.
 *
 * Returns 404 when no report exists yet — callers should handle this gracefully
 * and render a "no report available" state rather than an error.
 */
export async function getIntegrityReport(
  essayId: string,
): Promise<IntegrityReportResponse> {
  return apiGet<IntegrityReportResponse>(`/essays/${essayId}/integrity`);
}

/**
 * Update the teacher review status of an integrity report.
 * Calls PATCH /api/v1/integrity-reports/{reportId}/status.
 *
 * Only "reviewed_clear" and "flagged" are accepted.
 */
export async function updateIntegrityStatus(
  reportId: string,
  data: PatchIntegrityStatusRequest,
): Promise<IntegrityReportResponse> {
  return apiPatch<IntegrityReportResponse>(
    `/integrity-reports/${reportId}/status`,
    data,
  );
}

/**
 * Fetch class-level integrity signal counts for an assignment.
 * Calls GET /api/v1/assignments/{assignmentId}/integrity/summary.
 */
export async function getIntegritySummary(
  assignmentId: string,
): Promise<IntegritySummaryResponse> {
  return apiGet<IntegritySummaryResponse>(
    `/assignments/${assignmentId}/integrity/summary`,
  );
}
