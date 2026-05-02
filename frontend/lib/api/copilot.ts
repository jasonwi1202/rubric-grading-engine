/**
 * Teacher Copilot API helpers — M7-04 (Teacher Copilot UI).
 *
 * Covers:
 *   POST /copilot/query — answer a teacher's natural-language question using
 *                         live class data.
 *
 * Aligned with backend `app/schemas/copilot.py` response shapes.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 * - No student data is stored in localStorage / sessionStorage.
 * - The copilot is read-only: it never triggers grade changes or autonomous
 *   interventions. Only information is returned.
 */

import { apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types — aligned with backend app/schemas/copilot.py
// ---------------------------------------------------------------------------

/** Request body for POST /copilot/query. */
export interface CopilotQueryRequest {
  /** Natural-language question from the teacher (1–500 chars). */
  query: string;
  /** Optional class UUID to scope the context data. */
  class_id?: string | null;
}

/**
 * One ranked item surfaced by the copilot.
 * Matches backend CopilotRankedItemResponse exactly.
 */
export interface CopilotRankedItem {
  /** Student UUID, or null for skill-level items. */
  student_id: string | null;
  /** Resolved student display name, or null for skill-level items. */
  student_display_name: string | null;
  /** Canonical skill dimension (e.g. "thesis"), or null for student-level items. */
  skill_dimension: string | null;
  /** Short descriptive label for this ranked item. */
  label: string;
  /** Normalised signal strength in [0.0, 1.0], or null when not applicable. */
  value: number | null;
  /** Evidence-grounded explanation for this item's ranking. */
  explanation: string;
}

/** Response type returned by the copilot. */
export type CopilotResponseType = "ranked_list" | "summary" | "insufficient_data";

/**
 * Full copilot query response.
 * Matches backend CopilotQueryResponse exactly.
 */
export interface CopilotQueryResponse {
  /** One sentence summarising what the LLM understood the teacher to be asking. */
  query_interpretation: string;
  /** False when the class data is too sparse to produce a reliable answer. */
  has_sufficient_data: boolean;
  /** Human-readable explanation of data gaps, or null when data is sufficient. */
  uncertainty_note: string | null;
  /** Structured response type. */
  response_type: CopilotResponseType;
  /** Ranked list of students or skill dimensions most relevant to the query. */
  ranked_items: CopilotRankedItem[];
  /** 2–3 sentence overall answer to the teacher's question. */
  summary: string;
  /** Actionable follow-up steps for the teacher. */
  suggested_next_steps: string[];
  /** Versioned prompt module used to generate this response. */
  prompt_version: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Ask the teacher copilot a natural-language question about class data.
 * Calls POST /copilot/query.
 *
 * The copilot is read-only: it surfaces information but never takes action.
 */
export async function queryCopilot(
  body: CopilotQueryRequest,
): Promise<CopilotQueryResponse> {
  return apiPost<CopilotQueryResponse>("/copilot/query", body);
}
