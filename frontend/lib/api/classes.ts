/**
 * Classes & roster API helpers — M3 implementation.
 *
 * Covers all class CRUD operations and student roster management including
 * manual enrollment, soft-removal, and two-phase CSV import.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs are used in error paths.
 * - All endpoints require a valid JWT access token.
 */

import { apiDelete, apiGet, apiPatch, apiPost, apiPostForm } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// — Classes
// ---------------------------------------------------------------------------

export interface CreateClassRequest {
  name: string;
  subject: string;
  grade_level: string;
  academic_year: string;
}

export interface UpdateClassRequest {
  name?: string;
  subject?: string;
  grade_level?: string;
  academic_year?: string;
}

export interface ClassResponse {
  id: string;
  teacher_id: string;
  name: string;
  subject: string;
  grade_level: string;
  academic_year: string;
  is_archived: boolean;
  created_at: string;
  student_count?: number;
}

export interface ListClassesParams {
  academic_year?: string;
  is_archived?: boolean;
}

// ---------------------------------------------------------------------------
// — Students / Roster
// ---------------------------------------------------------------------------

/** Matches backend StudentResponse (student record, not enrollment). */
export interface StudentResponse {
  id: string;
  teacher_id: string;
  full_name: string;
  external_id: string | null;
  teacher_notes: string | null;
  created_at: string;
}

/** Matches backend EnrolledStudentResponse — enrollment wrapper + nested student. */
export interface EnrolledStudentResponse {
  enrollment_id: string;
  enrolled_at: string;
  student: StudentResponse;
}

export interface AddStudentRequest {
  full_name: string;
  external_id?: string;
}

// ---------------------------------------------------------------------------
// Types — Class Insights (M5.6 / M5.7)
// ---------------------------------------------------------------------------

/** Aggregated statistics for one canonical skill dimension. Matches backend SkillAverage. */
export interface SkillAverage {
  /** Mean normalised score in [0, 1] across all contributing essays. */
  avg_score: number;
  /** Number of students with at least one score. */
  student_count: number;
  /** Total individual criterion scores contributing. */
  data_points: number;
}

/** One histogram bucket for a score distribution. Matches backend ScoreBucket. */
export interface ScoreBucket {
  label: string;
  count: number;
}

/**
 * A skill dimension where the class average is below the concern threshold.
 * Matches backend CommonIssue exactly.
 */
export interface CommonIssue {
  skill_dimension: string;
  avg_score: number;
  affected_student_count: number;
}

/**
 * Response from GET /classes/{classId}/insights.
 * Matches backend ClassInsightsResponse exactly.
 */
export interface ClassInsightsResponse {
  class_id: string;
  assignment_count: number;
  student_count: number;
  graded_essay_count: number;
  /** Per-skill aggregated averages keyed by canonical skill dimension name. */
  skill_averages: Record<string, SkillAverage>;
  /** Per-skill score distribution keyed by canonical skill dimension name. */
  score_distributions: Record<string, ScoreBucket[]>;
  /** Skills below concern threshold, ranked by ascending avg_score. */
  common_issues: CommonIssue[];
}

// ---------------------------------------------------------------------------
// — CSV Roster Import (two-phase)
// ---------------------------------------------------------------------------

/** Per-row status from the CSV diff preview. */
export type CsvRowStatus = "new" | "updated" | "skipped" | "error";

/** Matches backend DiffRowResponse. */
export interface CsvImportRow {
  row_number: number;
  full_name: string;
  external_id: string | null;
  status: CsvRowStatus;
  message: string | null;
  existing_student_id: string | null;
}

/**
 * Matches backend ImportDiffResponse.
 * Counts are top-level flat fields, not a nested object.
 */
export interface CsvImportPreviewResponse {
  rows: CsvImportRow[];
  new_count: number;
  updated_count: number;
  skipped_count: number;
  error_count: number;
}

/** Rows sent back to the confirm endpoint — only the fields the backend expects. */
export interface ImportRowInput {
  row_number: number;
  full_name: string;
  external_id: string | null;
}

export interface CsvImportConfirmResponse {
  created: number;
  updated: number;
  skipped: number;
}

// ---------------------------------------------------------------------------
// API functions — Classes
// ---------------------------------------------------------------------------

/**
 * List all classes for the authenticated teacher.
 * Calls GET /api/v1/classes.
 */
export async function listClasses(
  params?: ListClassesParams,
): Promise<ClassResponse[]> {
  const query = new URLSearchParams();
  if (params?.academic_year) query.set("academic_year", params.academic_year);
  if (params?.is_archived !== undefined)
    query.set("is_archived", String(params.is_archived));
  const qs = query.toString();
  return apiGet<ClassResponse[]>(`/classes${qs ? `?${qs}` : ""}`);
}

/**
 * Create a new class for the authenticated teacher.
 * Calls POST /api/v1/classes.
 */
export async function createClass(
  data: CreateClassRequest,
): Promise<ClassResponse> {
  return apiPost<ClassResponse>("/classes", data);
}

/**
 * Get a single class with enrollment summary.
 * Calls GET /api/v1/classes/{classId}.
 */
export async function getClass(classId: string): Promise<ClassResponse> {
  return apiGet<ClassResponse>(`/classes/${classId}`);
}

/**
 * Update class metadata.
 * Calls PATCH /api/v1/classes/{classId}.
 */
export async function updateClass(
  classId: string,
  data: UpdateClassRequest,
): Promise<ClassResponse> {
  return apiPatch<ClassResponse>(`/classes/${classId}`, data);
}

/**
 * Archive a class (soft delete).
 * Calls POST /api/v1/classes/{classId}/archive.
 */
export async function archiveClass(classId: string): Promise<ClassResponse> {
  return apiPost<ClassResponse>(`/classes/${classId}/archive`, {});
}

// ---------------------------------------------------------------------------
// API functions — Students / Roster
// ---------------------------------------------------------------------------

/**
 * List enrolled students in a class.
 * Calls GET /api/v1/classes/{classId}/students.
 *
 * Backend returns enrolled-student wrappers; this helper returns the full
 * EnrolledStudentResponse so callers have access to both the student record
 * and the enrollment metadata (enrollment_id, enrolled_at).
 */
export async function listStudents(
  classId: string,
): Promise<EnrolledStudentResponse[]> {
  return apiGet<EnrolledStudentResponse[]>(`/classes/${classId}/students`);
}

/**
 * Manually enroll a new student in a class.
 * Calls POST /api/v1/classes/{classId}/students.
 */
export async function addStudent(
  classId: string,
  data: AddStudentRequest,
): Promise<EnrolledStudentResponse> {
  return apiPost<EnrolledStudentResponse>(`/classes/${classId}/students`, data);
}

/**
 * Soft-remove a student from a class.
 * Calls DELETE /api/v1/classes/{classId}/students/{studentId}.
 */
export async function removeStudent(
  classId: string,
  studentId: string,
): Promise<void> {
  return apiDelete<void>(`/classes/${classId}/students/${studentId}`);
}

// ---------------------------------------------------------------------------
// API functions — CSV Roster Import (two-phase)
// ---------------------------------------------------------------------------

/**
 * Phase 1: Upload a CSV file and receive a diff preview (no DB writes).
 * Calls POST /api/v1/classes/{classId}/students/import (multipart/form-data).
 *
 * Uses apiPostForm so the shared client's 401-refresh and error handling
 * are applied, and the browser sets the correct multipart boundary.
 */
export async function previewCsvImport(
  classId: string,
  file: File,
): Promise<CsvImportPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiPostForm<CsvImportPreviewResponse>(
    `/classes/${classId}/students/import`,
    formData,
  );
}

/**
 * Phase 2: Commit approved rows from the CSV diff.
 * Calls POST /api/v1/classes/{classId}/students/import/confirm.
 *
 * Only sends rows with status "new" or "updated"; each row is mapped to the
 * minimal shape the backend expects: { row_number, full_name, external_id }.
 */
export async function confirmCsvImport(
  classId: string,
  rows: ImportRowInput[],
): Promise<CsvImportConfirmResponse> {
  return apiPost<CsvImportConfirmResponse>(
    `/classes/${classId}/students/import/confirm`,
    { rows },
  );
}

// ---------------------------------------------------------------------------
// API functions — Class Insights
// ---------------------------------------------------------------------------

/**
 * Get class-level skill insights.
 * Calls GET /api/v1/classes/{classId}/insights.
 *
 * Returns aggregated skill averages, score distributions, and common issues
 * across all locked grades for all assignments in the class.
 */
export async function getClassInsights(
  classId: string,
): Promise<ClassInsightsResponse> {
  return apiGet<ClassInsightsResponse>(`/classes/${classId}/insights`);
}
