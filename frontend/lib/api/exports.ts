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

/** Response from POST /assignments/{assignmentId}/export (202 Accepted). */
export interface StartExportResponse {
  task_id: string;
  assignment_id: string;
  status: string;
}

/** Status of an async export task. */
export type ExportTaskStatus = "pending" | "processing" | "complete" | "failed";

/** Response from GET /exports/{taskId}/status. */
export interface ExportStatusResponse {
  task_id: string;
  status: ExportTaskStatus;
  /** Total number of essays to export. */
  total: number;
  /** Number of essays exported so far. */
  complete: number;
  /**
   * Error type code (e.g. "STORAGE_ERROR") when status is "failed".
   * Never contains raw exception messages or student PII.
   */
  error: string | null;
}

/** Response from GET /exports/{taskId}/download. */
export interface ExportDownloadResponse {
  /** Short-lived pre-signed S3 URL — do not store in browser storage. */
  url: string;
  /** Seconds until the URL expires (typically 900 = 15 min). */
  expires_in_seconds: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Enqueue an async PDF batch export for an assignment.
 * Calls POST /api/v1/assignments/{assignmentId}/export.
 * Returns a task_id immediately (202 Accepted).
 *
 * The backend endpoint takes no request body.
 */
export async function startExport(
  assignmentId: string,
): Promise<StartExportResponse> {
  return apiPost<StartExportResponse>(
    `/assignments/${assignmentId}/export`,
    {},
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
