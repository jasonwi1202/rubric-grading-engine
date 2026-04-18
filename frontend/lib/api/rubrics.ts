/**
 * Rubrics API helpers — stub for M3 implementation.
 *
 * The full CRUD implementation lives in M3. This stub exposes only the
 * `createRubric` function needed by the onboarding wizard (Step 2).
 *
 * Security notes:
 * - No student PII is collected or processed in this module.
 * - These endpoints require a valid JWT access token.
 */

import { apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RubricCriterionRequest {
  name: string;
  description?: string;
  weight: number;
  min_score: number;
  max_score: number;
}

export interface CreateRubricRequest {
  name: string;
  criteria: RubricCriterionRequest[];
}

export interface RubricResponse {
  id: string;
  name: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Create a new rubric for the authenticated teacher.
 * Calls POST /api/v1/rubrics (M3 endpoint).
 */
export async function createRubric(
  data: CreateRubricRequest,
): Promise<RubricResponse> {
  return apiPost<RubricResponse>("/rubrics", data);
}
