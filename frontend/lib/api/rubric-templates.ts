/**
 * Rubric templates API helpers — M3.4 implementation.
 *
 * Security notes:
 * - No student PII is collected or processed in this module.
 * - These endpoints require a valid JWT access token.
 */

import { apiGet, apiPost } from "@/lib/api/client";
import type { RubricCriterionResponse } from "@/lib/api/rubrics";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Summary item returned by GET /api/v1/rubric-templates.
 */
export interface RubricTemplateListItem {
  id: string;
  name: string;
  description: string | null;
  /** True when this is a system-provided starter template. */
  is_system: boolean;
  created_at: string;
  updated_at: string;
  criterion_count: number;
}

/**
 * Full template response including criteria.
 */
export interface RubricTemplateResponse {
  id: string;
  name: string;
  description: string | null;
  /** True when this is a system-provided starter template. */
  is_system: boolean;
  created_at: string;
  updated_at: string;
  criteria: RubricCriterionResponse[];
}

export interface SaveRubricAsTemplateRequest {
  /** ID of the source rubric to copy as a template. */
  rubric_id: string;
  /** Optional name override; defaults to the source rubric name. */
  name?: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * List all system templates and the authenticated teacher's personal templates.
 * Calls GET /api/v1/rubric-templates.
 */
export async function listRubricTemplates(): Promise<RubricTemplateListItem[]> {
  return apiGet<RubricTemplateListItem[]>("/rubric-templates");
}

/**
 * Save an existing rubric as a personal template.
 * Calls POST /api/v1/rubric-templates.
 */
export async function saveRubricAsTemplate(
  data: SaveRubricAsTemplateRequest,
): Promise<RubricTemplateResponse> {
  return apiPost<RubricTemplateResponse>("/rubric-templates", data);
}

/**
 * Get a single template with its full criteria list.
 * System templates are accessible to any authenticated teacher.
 * Calls GET /api/v1/rubric-templates/{templateId}.
 */
export async function getRubricTemplate(
  templateId: string,
): Promise<RubricTemplateResponse> {
  return apiGet<RubricTemplateResponse>(`/rubric-templates/${templateId}`);
}
