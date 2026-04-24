/**
 * Media comments API helpers — M4.10 (Audio comment recording and storage).
 *
 * Covers:
 *   POST   /grades/{gradeId}/media-comments   — upload blob, create record
 *   GET    /grades/{gradeId}/media-comments   — list comments for a grade
 *   DELETE /media-comments/{id}               — delete record + S3 object
 *   GET    /media-comments/{id}/url           — presigned playback URL
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

import { apiDelete, apiGet, apiPostForm } from "@/lib/api/client";

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
  created_at: string;
}

/**
 * Response from GET /media-comments/{id}/url.
 * Matches backend `MediaCommentUrlResponse` exactly.
 */
export interface MediaCommentUrlResponse {
  url: string;
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
