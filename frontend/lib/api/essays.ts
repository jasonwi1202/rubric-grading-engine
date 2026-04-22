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
  file_storage_key: string | null;
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

/**
 * Essay list item enriched with grade summary for the review queue (M3.22).
 *
 * `total_score`, `max_possible_score`, and `grade_id` are null when the essay
 * has not been graded yet. Callers should treat null as "ungraded" and sort
 * such essays after all scored essays when sorting by score.
 *
 * These fields are returned by the same GET /assignments/{id}/essays endpoint
 * when the essay is in a graded state; they are absent (null) otherwise.
 */
export interface ReviewQueueEssay extends EssayListItem {
  /** Total score string from the grade record, e.g. "7.00". Null if ungraded. */
  total_score: string | null;
  /** Max possible score string, e.g. "10.00". Null if ungraded. */
  max_possible_score: string | null;
  /** Grade UUID. Null if the essay has not been graded yet. */
  grade_id: string | null;
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
 * - `text` is converted to a TXT blob and appended as a file part, so it is
 *   handled by the same multipart upload endpoint that processes file uploads.
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
  // Convert pasted text to a plain-text file so the existing upload endpoint
  // (which requires `files`) handles both input modes uniformly.
  if (payload.text) {
    const textBlob = new Blob([payload.text], { type: "text/plain" });
    formData.append("files", textBlob, "essay.txt");
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

/**
 * List all essays for an assignment with grade summary data for the review
 * queue (M3.22). Calls GET /api/v1/assignments/{assignmentId}/essays.
 *
 * Returns ReviewQueueEssay items: each item extends EssayListItem with
 * optional grade summary fields (total_score, max_possible_score, grade_id).
 * These fields are null when the essay has not been graded.
 */
export async function listReviewQueue(
  assignmentId: string,
): Promise<ReviewQueueEssay[]> {
  return apiGet<ReviewQueueEssay[]>(`/assignments/${assignmentId}/essays`);
}
