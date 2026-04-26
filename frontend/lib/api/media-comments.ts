/**
 * Media comments API helpers — M4.10 (Audio comment recording and storage),
 * M4.12 (Media comment bank and export).
 *
 * Covers:
 *   POST   /grades/{gradeId}/media-comments          — upload blob, create record
 *                                                      OR apply banked comment via source_id
 *   GET    /grades/{gradeId}/media-comments          — list comments for a grade
 *   DELETE /media-comments/{id}                      — delete record + S3 object
 *   GET    /media-comments/{id}/url                  — presigned playback URL
 *   POST   /media-comments/{id}/save-to-bank         — mark comment as banked
 *   GET    /media-comments/bank                      — list all banked comments
 *
 * Upload flow:
 *   The audio blob is sent as multipart/form-data to the backend, which
 *   uploads it to S3 and returns the created record.  S3 credentials
 *   never leave the server.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 * - No audio content or student data is stored client-side.
 */

import { apiDelete, apiGet, apiPost, apiPostForm } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * A single media comment record.
 * Matches backend `MediaCommentResponse` exactly.
 */
export interface MediaCommentResponse {
  id: string;
  grade_id: string;
  s3_key: string;
  duration_seconds: number;
  mime_type: string;
  is_banked: boolean;
  created_at: string;
}

/**
 * Response from GET /media-comments/{id}/url.
 * Matches backend `MediaCommentUrlResponse` exactly.
 */
export interface MediaCommentUrlResponse {
  url: string;
}

/**
 * Response from POST /media-comments/{id}/save-to-bank.
 * Matches backend `SaveToBankResponse` exactly.
 */
export interface SaveToBankResponse {
  id: string;
  is_banked: boolean;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Upload an audio blob and create a media comment record.
 *
 * Sends the blob as multipart/form-data; the backend handles S3 upload.
 * Calls POST /api/v1/grades/{gradeId}/media-comments.
 */
export async function uploadMediaComment(
  gradeId: string,
  blob: Blob,
  durationSeconds: number,
): Promise<MediaCommentResponse> {
  const form = new FormData();
  form.append("file", blob, "recording.webm");
  form.append("duration_seconds", String(durationSeconds));
  return apiPostForm<MediaCommentResponse>(
    `/grades/${gradeId}/media-comments`,
    form,
  );
}

/**
 * Apply a banked media comment to a grade (no new recording needed).
 *
 * Sends source_id as multipart/form-data; the backend copies the S3 object.
 * Calls POST /api/v1/grades/{gradeId}/media-comments with source_id.
 */
export async function applyBankedComment(
  gradeId: string,
  sourceId: string,
): Promise<MediaCommentResponse> {
  const form = new FormData();
  form.append("source_id", sourceId);
  return apiPostForm<MediaCommentResponse>(
    `/grades/${gradeId}/media-comments`,
    form,
  );
}

/**
 * List all media comments for a grade.
 * Calls GET /api/v1/grades/{gradeId}/media-comments.
 */
export async function listGradeMediaComments(
  gradeId: string,
): Promise<MediaCommentResponse[]> {
  return apiGet<MediaCommentResponse[]>(`/grades/${gradeId}/media-comments`);
}

/**
 * Delete a media comment record and its S3 object.
 * Calls DELETE /api/v1/media-comments/{id}.
 */
export async function deleteMediaComment(id: string): Promise<void> {
  return apiDelete<void>(`/media-comments/${id}`);
}

/**
 * Fetch an access-controlled presigned URL for playback.
 * Calls GET /api/v1/media-comments/{id}/url.
 */
export async function getMediaCommentUrl(
  id: string,
): Promise<MediaCommentUrlResponse> {
  return apiGet<MediaCommentUrlResponse>(`/media-comments/${id}/url`);
}

/**
 * Save a media comment to the teacher's reusable bank.
 * Calls POST /api/v1/media-comments/{id}/save-to-bank.
 */
export async function saveToBank(id: string): Promise<SaveToBankResponse> {
  return apiPost<SaveToBankResponse>(`/media-comments/${id}/save-to-bank`, {});
}

/**
 * List all banked (reusable) media comments for the authenticated teacher.
 * Calls GET /api/v1/media-comments/bank.
 */
export async function listBankedComments(): Promise<MediaCommentResponse[]> {
  return apiGet<MediaCommentResponse[]>(`/media-comments/bank`);
}
