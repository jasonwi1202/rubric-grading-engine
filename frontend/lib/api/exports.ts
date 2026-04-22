/**
 * Exports API helpers — M3.26 (Export UI).
 *
 * Covers:
 *   POST /assignments/{assignmentId}/export       — enqueue async PDF ZIP export
 *   GET  /exports/{taskId}/status                 — poll export task status
 *   GET  /exports/{taskId}/download               — fetch pre-signed S3 download URL
 *   GET  /assignments/{assignmentId}/grades.csv   — synchronous CSV grade export
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear in error paths.
 * - Pre-signed download URLs are short-lived and must not be stored in browser storage.
 * - CSV content is held only in memory (Blob) and never written to browser storage.
 * - All endpoints require a valid JWT access token.
 */

import { apiGet, apiGetBlob, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Request body for POST /assignments/{assignmentId}/export. */
export interface StartExportRequest {
  format: "pdf";
  /** UUIDs of students to include, or "all" to export every locked grade. */
  student_ids?: string[] | "all";
}

/** Response from POST /assignments/{assignmentId}/export (202 Accepted). */
export interface StartExportResponse {
  task_id: string;
}

/** Status of an async export task. */
export type ExportTaskStatus = "pending" | "processing" | "complete" | "failed";

/** Response from GET /exports/{taskId}/status. */
export interface ExportStatusResponse {
  task_id: string;
  status: ExportTaskStatus;
  /** Progress percentage 0–100, or null when not yet determined. */
  progress: number | null;
  /**
   * Error type code (e.g. "STORAGE_ERROR") when status is "failed".
   * Never contains raw exception messages or student PII.
   */
  error: string | null;
}

/** Response from GET /exports/{taskId}/download. */
export interface ExportDownloadResponse {
  /** Short-lived pre-signed S3 URL — do not store in browser storage. */
  download_url: string;
  /** ISO 8601 timestamp when the URL expires. */
  expires_at: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Enqueue an async PDF batch export for an assignment.
 * Calls POST /api/v1/assignments/{assignmentId}/export.
 * Returns a task_id immediately (202 Accepted).
 */
export async function startExport(
  assignmentId: string,
  data: StartExportRequest = { format: "pdf", student_ids: "all" },
): Promise<StartExportResponse> {
  return apiPost<StartExportResponse>(
    `/assignments/${assignmentId}/export`,
    data,
  );
}

/**
 * Poll the status of an async export task.
 * Calls GET /api/v1/exports/{taskId}/status.
 */
export async function getExportStatus(
  taskId: string,
): Promise<ExportStatusResponse> {
  return apiGet<ExportStatusResponse>(`/exports/${taskId}/status`);
}

/**
 * Get the pre-signed S3 download URL for a completed export.
 * Calls GET /api/v1/exports/{taskId}/download.
 *
 * The URL is short-lived — do not store it in localStorage, sessionStorage,
 * or cookies.
 */
export async function getExportDownloadUrl(
  taskId: string,
): Promise<ExportDownloadResponse> {
  return apiGet<ExportDownloadResponse>(`/exports/${taskId}/download`);
}

/**
 * Download grades as a CSV file (synchronous export).
 * Calls GET /api/v1/assignments/{assignmentId}/grades.csv.
 *
 * Triggers a browser save dialog by creating a temporary object URL from
 * the response blob. The CSV content is only held in memory — it is never
 * written to localStorage, sessionStorage, or cookies.
 */
export async function downloadGradesCsv(assignmentId: string): Promise<void> {
  const blob = await apiGetBlob(`/assignments/${assignmentId}/grades.csv`);
  const objectUrl = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `grades-${assignmentId}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
