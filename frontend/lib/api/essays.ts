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

import { apiGet, apiPatch, apiPost, apiPostForm } from "@/lib/api/client";
import type { ConfidenceLevel } from "@/lib/api/grades";

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
 * `total_score`, `max_possible_score`, and `grade_id` are absent (`undefined`)
 * when the backend does not (yet) return them, and `null` when the essay has
 * been graded but the field has no value. Callers must treat both `null` and
 * `undefined` as "ungraded / unavailable" (i.e. use `== null` checks).
 *
 * Note: the current backend `EssayListItemResponse` does not include these
 * fields. They are typed here as optional so the frontend degrades gracefully
 * (shows "—" score) until a backend endpoint that returns grade summaries is
 * available.
 */
export interface ReviewQueueEssay extends EssayListItem {
  /** Total score string from the grade record, e.g. "7.00". Absent or null if ungraded. */
  total_score?: string | null;
  /** Max possible score string, e.g. "10.00". Absent or null if ungraded. */
  max_possible_score?: string | null;
  /** Grade UUID. Absent or null if the essay has not been graded yet. */
  grade_id?: string | null;
  /**
   * Overall confidence derived from criterion confidence levels.
   * Absent or null for essays that have not been graded or for grades created
   * before M4.1. Callers must treat both `null` and `undefined` as unavailable.
   */
  overall_confidence?: ConfidenceLevel | null;
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

// ---------------------------------------------------------------------------
// Browser composition — M5-09
// ---------------------------------------------------------------------------

/** Request body for POST /assignments/{id}/essays/compose */
export interface ComposeEssayRequest {
  student_id?: string | null;
}

/** Response from POST /assignments/{id}/essays/compose */
export interface ComposedEssay {
  essay_id: string;
  essay_version_id: string;
  assignment_id: string;
  student_id: string | null;
  status: string;
  current_content: string;
  word_count: number;
}

/** Request body for POST /essays/{id}/snapshots */
export interface WriteSnapshotRequest {
  html_content: string;
  word_count: number;
}

/** Response from POST /essays/{id}/snapshots */
export interface WriteSnapshotResponse {
  essay_id: string;
  essay_version_id: string;
  snapshot_count: number;
  word_count: number;
  saved_at: string;
}

/** One snapshot's metadata (no html_content returned in list) */
export interface SnapshotItem {
  seq: number;
  ts: string;
  word_count: number;
}

/** Response from GET /essays/{id}/snapshots */
export interface EssaySnapshotState {
  essay_id: string;
  essay_version_id: string;
  /** Latest HTML content for editor restoration after refresh */
  current_content: string;
  word_count: number;
  snapshots: SnapshotItem[];
}

/**
 * Create a blank essay for in-browser composition.
 * Calls POST /api/v1/assignments/{assignmentId}/essays/compose.
 *
 * Returns the new essay_id and essay_version_id so the writing interface
 * can immediately start saving snapshots.
 */
export async function createComposedEssay(
  assignmentId: string,
  payload: ComposeEssayRequest = {},
): Promise<ComposedEssay> {
  return apiPost<ComposedEssay>(`/assignments/${assignmentId}/essays/compose`, payload);
}

/**
 * Save a writing-process snapshot (autosave tick).
 * Calls POST /api/v1/essays/{essayId}/snapshots.
 *
 * Security: the content is sent to the backend only; never stored in browser
 * storage (localStorage / sessionStorage / cookies).
 */
export async function saveSnapshot(
  essayId: string,
  data: WriteSnapshotRequest,
): Promise<WriteSnapshotResponse> {
  return apiPost<WriteSnapshotResponse>(`/essays/${essayId}/snapshots`, data);
}

/**
 * Retrieve writing snapshots for editor state recovery after refresh.
 * Calls GET /api/v1/essays/{essayId}/snapshots.
 */
export async function getSnapshots(essayId: string): Promise<EssaySnapshotState> {
  return apiGet<EssaySnapshotState>(`/essays/${essayId}/snapshots`);
}

/**
 * List essays for the review queue using the current assignment essays
 * endpoint. Calls GET /assignments/{assignmentId}/essays.
 *
 * This endpoint currently matches `listEssays()` and returns the standard
 * essay list payload. The `ReviewQueueEssay` type lets review UI code handle
 * optional grade summary fields when they are available, but callers must not
 * assume `total_score`, `max_possible_score`, or `grade_id` are returned by
 * the backend today; treat absent or null values as "ungraded / unavailable".
 */
export async function listReviewQueue(
  assignmentId: string,
): Promise<ReviewQueueEssay[]> {
  return apiGet<ReviewQueueEssay[]>(`/assignments/${assignmentId}/essays`);
}
