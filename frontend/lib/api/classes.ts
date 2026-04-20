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

import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth/session";
import { getBaseUrl } from "@/lib/api/baseFetch";
import { ApiError } from "@/lib/api/errors";
import type { ApiErrorBody } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CreateClassRequest {
  name: string;
  grade_level: string;
  academic_year?: string;
}

export interface UpdateClassRequest {
  name?: string;
  grade_level?: string;
  academic_year?: string;
}

export interface ClassResponse {
  id: string;
  name: string;
  grade_level: string;
  academic_year: string | null;
  is_archived: boolean;
  created_at: string;
  student_count?: number;
}

export interface StudentResponse {
  id: string;
  full_name: string;
  external_id: string | null;
  enrolled_at: string;
  is_active: boolean;
}

export interface AddStudentRequest {
  full_name: string;
  external_id?: string;
}

/** Per-row status from the CSV diff preview. */
export type CsvRowStatus = "new" | "updated" | "skipped" | "error";

export interface CsvImportRow {
  row_number: number;
  full_name: string;
  external_id: string | null;
  status: CsvRowStatus;
  message: string | null;
}

export interface CsvImportPreviewResponse {
  rows: CsvImportRow[];
  counts: {
    new: number;
    updated: number;
    skipped: number;
    error: number;
  };
}

export interface CsvImportConfirmResponse {
  created: number;
  updated: number;
  skipped: number;
}

export interface ListClassesParams {
  academic_year?: string;
  is_archived?: boolean;
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
 */
export async function listStudents(
  classId: string,
): Promise<StudentResponse[]> {
  return apiGet<StudentResponse[]>(`/classes/${classId}/students`);
}

/**
 * Manually enroll a new student in a class.
 * Calls POST /api/v1/classes/{classId}/students.
 */
export async function addStudent(
  classId: string,
  data: AddStudentRequest,
): Promise<StudentResponse> {
  return apiPost<StudentResponse>(`/classes/${classId}/students`, data);
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
 * Uses raw fetch because the body is multipart, not JSON.
 */
export async function previewCsvImport(
  classId: string,
  file: File,
): Promise<CsvImportPreviewResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const url = `${getBaseUrl()}/classes/${classId}/students/import`;
  const token = getAccessToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: formData,
    credentials: "include",
  });

  if (!response.ok) {
    let errorBody: ApiErrorBody;
    try {
      const json = (await response.json()) as { error?: ApiErrorBody };
      errorBody = json.error ?? {
        code: "UNKNOWN_ERROR",
        message: response.statusText,
      };
    } catch {
      errorBody = { code: "UNKNOWN_ERROR", message: response.statusText };
    }
    throw new ApiError(response.status, errorBody);
  }

  const json = (await response.json()) as {
    data: CsvImportPreviewResponse;
  };
  return json.data;
}

/**
 * Phase 2: Commit approved rows from the CSV diff.
 * Calls POST /api/v1/classes/{classId}/students/import/confirm.
 */
export async function confirmCsvImport(
  classId: string,
  rows: CsvImportRow[],
): Promise<CsvImportConfirmResponse> {
  return apiPost<CsvImportConfirmResponse>(
    `/classes/${classId}/students/import/confirm`,
    { rows },
  );
}
