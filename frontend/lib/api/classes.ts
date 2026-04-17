/**
 * Classes API helpers — stub for M3 implementation.
 *
 * The full CRUD implementation lives in M3. This stub exposes only the
 * `createClass` function needed by the onboarding wizard (Step 1).
 *
 * Security notes:
 * - No student PII is collected or processed in this module.
 * - These endpoints require a valid JWT access token.
 */

import { apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CreateClassRequest {
  name: string;
  grade_level: string;
  academic_year?: string;
}

export interface ClassResponse {
  id: string;
  name: string;
  grade_level: string;
  academic_year: string | null;
  is_archived: boolean;
  created_at: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Create a new class for the authenticated teacher.
 * Calls POST /api/v1/classes (M3 endpoint).
 */
export async function createClass(
  data: CreateClassRequest,
): Promise<ClassResponse> {
  return apiPost<ClassResponse>("/classes", data);
}
