/**
 * Rubrics API helpers — full CRUD implementation for M3.
 *
 * Security notes:
 * - No student PII is collected or processed in this module.
 * - These endpoints require a valid JWT access token.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Score-level anchor descriptions keyed by score value (as string). */
export type AnchorDescriptions = Record<string, string>;

export interface RubricCriterionRequest {
  name: string;
  description?: string;
  weight: number;
  min_score: number;
  max_score: number;
  anchor_descriptions?: AnchorDescriptions | null;
}

export interface CreateRubricRequest {
  name: string;
  criteria: RubricCriterionRequest[];
}

export interface UpdateRubricRequest {
  name?: string;
  criteria?: RubricCriterionRequest[];
}

export interface RubricCriterionResponse {
  id: string;
  name: string;
  description: string;
  weight: number;
  min_score: number;
  max_score: number;
  display_order: number;
  anchor_descriptions: AnchorDescriptions | null;
}

export interface RubricResponse {
  id: string;
  name: string;
  description: string | null;
  is_template: boolean;
  created_at: string;
  updated_at: string;
  criteria: RubricCriterionResponse[];
}

export interface RubricDetailResponse {
  id: string;
  name: string;
  created_at: string;
  criteria: RubricCriterionResponse[];
}

export interface RubricListItem {
  id: string;
  name: string;
  created_at: string;
  criterion_count: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * List all rubrics for the authenticated teacher.
 * Calls GET /api/v1/rubrics.
 */
export async function listRubrics(): Promise<RubricListItem[]> {
  return apiGet<RubricListItem[]>("/rubrics");
}

/**
 * Get a single rubric with all criteria.
 * Calls GET /api/v1/rubrics/{rubricId}.
 */
export async function getRubric(rubricId: string): Promise<RubricDetailResponse> {
  return apiGet<RubricDetailResponse>(`/rubrics/${rubricId}`);
}

/**
 * Create a new rubric for the authenticated teacher.
 * Calls POST /api/v1/rubrics.
 */
export async function createRubric(
  data: CreateRubricRequest,
): Promise<RubricResponse> {
  return apiPost<RubricResponse>("/rubrics", data);
}

/**
 * Update a rubric's name and/or criteria.
 * Calls PATCH /api/v1/rubrics/{rubricId}.
 */
export async function updateRubric(
  rubricId: string,
  data: UpdateRubricRequest,
): Promise<RubricResponse> {
  return apiPatch<RubricResponse>(`/rubrics/${rubricId}`, data);
}

/**
 * Soft-delete a rubric (blocked if in use by an open assignment).
 * Calls DELETE /api/v1/rubrics/{rubricId}.
 */
export async function deleteRubric(rubricId: string): Promise<void> {
  return apiDelete<void>(`/rubrics/${rubricId}`);
}
