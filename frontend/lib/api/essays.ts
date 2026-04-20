/**
 * Essays API helpers — M3.11 implementation.
 *
 * Covers essay upload (file and text-paste), listing, and manual student
 * assignment (the manual-correction step of the auto-assignment review flow).
 *
 * Security notes:
 * - No essay content, file names, or student PII are logged; only entity IDs.
 * - All endpoints require a valid JWT access token.
 * - File type and size are validated client-side (Zod) and server-side (MIME).
 */

import { apiGet, apiPatch, apiPostForm } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The outcome of the server-side auto-assignment attempt. */
export type AutoAssignStatus = "assigned" | "ambiguous" | "unassigned" | null;

/** One item returned by POST /assignments/{id}/essays. */
export interface EssayUploadResult {
  essay_id: string;
  essay_version_id: string;
  assignment_id: string;
  student_id: string | null;
  status: string;
  word_count: number;
  file_storage_key: string;
  submitted_at: string;
  auto_assign_status: AutoAssignStatus;
}

/** One item returned by GET /assignments/{id}/essays. */
export interface EssayListItem {
  essay_id: string;
  assignment_id: string;
  student_id: string | null;
  student_name: string | null;
  status: string;
  word_count: number;
  submitted_at: string;
  auto_assign_status: AutoAssignStatus;
}

/** PATCH /essays/{essayId} request body. */
export interface AssignEssayRequest {
  student_id: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Upload one or more essay files and/or a paste-text essay to an assignment.
 *
 * Calls POST /api/v1/assignments/{assignmentId}/essays (multipart/form-data).
 *
 * - `files` are appended as separate `files` parts (one per file).
 * - `text` is appended as a plain-text `text` part when provided.
 * - `student_id` is included only when the caller passes it (bypasses auto-assignment).
 *
 * Uses apiPostForm so the shared client's 401-refresh and error handling
 * apply, and the browser sets the correct multipart boundary automatically.
 */
export async function uploadEssays(
  assignmentId: string,
  payload: { files?: File[]; text?: string; studentId?: string },
): Promise<EssayUploadResult[]> {
  const formData = new FormData();
  for (const file of payload.files ?? []) {
    formData.append("files", file);
  }
  if (payload.text) {
    formData.append("text", payload.text);
  }
  if (payload.studentId) {
    formData.append("student_id", payload.studentId);
  }
  return apiPostForm<EssayUploadResult[]>(
    `/assignments/${assignmentId}/essays`,
    formData,
  );
}

/**
 * List all essays for an assignment with status and student assignment.
 * Calls GET /api/v1/assignments/{assignmentId}/essays.
 */
export async function listEssays(
  assignmentId: string,
): Promise<EssayListItem[]> {
  return apiGet<EssayListItem[]>(`/assignments/${assignmentId}/essays`);
}

/**
 * Manually assign an essay to a student (manual-correction step).
 * Calls PATCH /api/v1/essays/{essayId}.
 */
export async function assignEssay(
  essayId: string,
  data: AssignEssayRequest,
): Promise<EssayListItem> {
  return apiPatch<EssayListItem>(`/essays/${essayId}`, data);
}
