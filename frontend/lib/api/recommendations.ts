/**
 * Instruction Recommendations API helpers — M6-09 (Instruction Recommendations UI).
 *
 * Covers:
 *   POST /students/{studentId}/recommendations          — generate for student profile
 *   GET  /students/{studentId}/recommendations          — list persisted recs for student
 *   POST /classes/{classId}/groups/{groupId}/recommendations — generate for skill-gap group
 *   POST /recommendations/{recommendationId}/assign     — teacher-confirmed assignment
 *   POST /recommendations/{recommendationId}/dismiss    — teacher dismissal
 *
 * Aligned with backend `app/schemas/instruction_recommendation.py` response shapes.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 * - No student data is stored in localStorage / sessionStorage.
 */

import { apiGet, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Teacher review lifecycle for a recommendation set. */
export type RecommendationStatus = "pending_review" | "accepted" | "dismissed";

/**
 * A single activity recommendation within a generated set.
 * Matches backend `RecommendationItemResponse` exactly.
 */
export interface RecommendationItemResponse {
  /** Canonical skill dimension targeted (e.g. 'thesis'). */
  skill_dimension: string;
  /** Short activity title — serves as the objective. */
  title: string;
  /** Specific, actionable activity description — the structure. */
  description: string;
  /** Estimated activity duration in minutes. */
  estimated_minutes: number;
  /** Instructional strategy label, e.g. 'mini_lesson', 'guided_practice'. */
  strategy_type: string;
}

/**
 * Full instruction recommendation set as returned by the API.
 * Matches backend `InstructionRecommendationResponse` exactly.
 */
export interface InstructionRecommendationResponse {
  id: string;
  teacher_id: string;
  student_id: string | null;
  group_id: string | null;
  worklist_item_id: string | null;
  skill_key: string | null;
  grade_level: string;
  prompt_version: string;
  recommendations: RecommendationItemResponse[];
  evidence_summary: string;
  status: RecommendationStatus;
  created_at: string;
}

/** Request body for POST /students/{studentId}/recommendations. */
export interface GenerateStudentRecommendationRequest {
  /** Grade-level descriptor, e.g. 'Grade 8'. */
  grade_level: string;
  /** Target activity duration in minutes (5–120, default 20). */
  duration_minutes?: number;
  /** Optionally restrict generation to a single skill dimension. */
  skill_key?: string | null;
  /** ID of the worklist item that triggered this generation. */
  worklist_item_id?: string | null;
}

/** Request body for POST /classes/{classId}/groups/{groupId}/recommendations. */
export interface GenerateGroupRecommendationRequest {
  /** Grade-level descriptor, e.g. 'Grade 8'. */
  grade_level: string;
  /** Target activity duration in minutes (5–120, default 20). */
  duration_minutes?: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Generate instruction recommendations from a student's skill profile.
 * Calls POST /students/{studentId}/recommendations.
 */
export async function generateStudentRecommendations(
  studentId: string,
  body: GenerateStudentRecommendationRequest,
): Promise<InstructionRecommendationResponse> {
  return apiPost<InstructionRecommendationResponse>(
    `/students/${studentId}/recommendations`,
    body,
  );
}

/**
 * List all persisted recommendation sets for a student, newest-first.
 * Calls GET /students/{studentId}/recommendations.
 */
export async function listStudentRecommendations(
  studentId: string,
): Promise<InstructionRecommendationResponse[]> {
  return apiGet<InstructionRecommendationResponse[]>(
    `/students/${studentId}/recommendations`,
  );
}

/**
 * Generate instruction recommendations for a class skill-gap group.
 * Calls POST /classes/{classId}/groups/{groupId}/recommendations.
 */
export async function generateGroupRecommendations(
  classId: string,
  groupId: string,
  body: GenerateGroupRecommendationRequest,
): Promise<InstructionRecommendationResponse> {
  return apiPost<InstructionRecommendationResponse>(
    `/classes/${classId}/groups/${groupId}/recommendations`,
    body,
  );
}

/**
 * Record the teacher's explicit confirmation to assign an instruction recommendation.
 * Transitions status from 'pending_review' → 'accepted'.
 * Calls POST /recommendations/{recommendationId}/assign.
 */
export async function assignRecommendation(
  recommendationId: string,
): Promise<InstructionRecommendationResponse> {
  return apiPost<InstructionRecommendationResponse>(
    `/recommendations/${recommendationId}/assign`,
    {},
  );
}

/**
 * Record the teacher's explicit dismissal of an instruction recommendation.
 * Transitions status from 'pending_review' → 'dismissed'.
 * Calls POST /recommendations/{recommendationId}/dismiss.
 */
export async function dismissRecommendation(
  recommendationId: string,
): Promise<InstructionRecommendationResponse> {
  return apiPost<InstructionRecommendationResponse>(
    `/recommendations/${recommendationId}/dismiss`,
    {},
  );
}
