/**
 * Students API helpers — M5.5 (Student profile UI).
 *
 * Covers:
 *   GET   /students/{studentId}          — student detail with embedded skill profile
 *   GET   /students/{studentId}/history  — locked graded assignment history (newest-first)
 *   PATCH /students/{studentId}          — update student name, external ID, or teacher notes
 *
 * Aligned with backend `app/schemas/student.py` response shapes.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 * - Teacher notes are private to the teacher — never shared with students.
 * - No student data is stored in localStorage / sessionStorage.
 */

import { apiGet, apiPatch } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types — Skill Profile
// ---------------------------------------------------------------------------

/** Trend direction for a single skill dimension. */
export type SkillTrend = "improving" | "stable" | "declining";

/**
 * Per-skill-dimension data within a student's skill profile.
 * Matches backend `SkillDimensionResponse` exactly.
 */
export interface SkillDimensionResponse {
  /** Weighted average score in [0, 1]. */
  avg_score: number;
  /** Direction of recent performance change. */
  trend: SkillTrend;
  /** Number of criterion scores contributing to this average. */
  data_points: number;
  /** ISO-8601 timestamp of the most recent score. */
  last_updated: string;
}

/**
 * Aggregated skill profile embedded in the student detail response.
 * Matches backend `SkillProfileResponse` exactly.
 */
export interface SkillProfileResponse {
  /** Map of canonical skill name → dimension data. */
  skill_scores: Record<string, SkillDimensionResponse>;
  /** Total graded assignments contributing to this profile. */
  assignment_count: number;
  /** ISO-8601 timestamp of the last profile update. */
  last_updated_at: string;
}

// ---------------------------------------------------------------------------
// Types — Student
// ---------------------------------------------------------------------------

/**
 * Student detail with an optional embedded skill profile.
 * Matches backend `StudentWithProfileResponse` exactly.
 *
 * `skill_profile` is `null` when the student has no locked grades yet.
 */
export interface StudentWithProfileResponse {
  id: string;
  teacher_id: string;
  full_name: string;
  external_id: string | null;
  teacher_notes: string | null;
  created_at: string;
  skill_profile: SkillProfileResponse | null;
}

/**
 * A single locked graded assignment in a student's history.
 * Matches backend `AssignmentHistoryItemResponse` exactly.
 */
export interface AssignmentHistoryItem {
  assignment_id: string;
  assignment_title: string;
  class_id: string;
  grade_id: string;
  essay_id: string;
  total_score: number;
  max_possible_score: number;
  /** ISO-8601 datetime string. */
  locked_at: string;
}

/** Request body for PATCH /students/{studentId}. */
export interface PatchStudentRequest {
  full_name?: string;
  external_id?: string | null;
  teacher_notes?: string | null;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch a student with their embedded skill profile.
 * Calls GET /students/{studentId}.
 *
 * Returns the student record and, when available, the aggregated skill profile.
 * `skill_profile` is `null` if the student has no locked grades.
 */
export async function getStudentWithProfile(
  studentId: string,
): Promise<StudentWithProfileResponse> {
  return apiGet<StudentWithProfileResponse>(`/students/${studentId}`);
}

/**
 * Fetch all locked graded assignments for a student, newest-first.
 * Calls GET /students/{studentId}/history.
 */
export async function getStudentHistory(
  studentId: string,
): Promise<AssignmentHistoryItem[]> {
  return apiGet<AssignmentHistoryItem[]>(`/students/${studentId}/history`);
}

/**
 * Partially update a student record.
 * Calls PATCH /students/{studentId}.
 *
 * Only fields explicitly included in the request body are updated.
 * To clear `external_id` or `teacher_notes`, send the field as `null`.
 */
export async function patchStudent(
  studentId: string,
  data: PatchStudentRequest,
): Promise<StudentWithProfileResponse> {
  return apiPatch<StudentWithProfileResponse>(`/students/${studentId}`, data);
}
