"use client";

/**
 * ExportPanel — batch export controls for an assignment.
 *
 * Features:
 * - "Export" button that opens an option panel.
 * - PDF batch ZIP export (async): enqueues a Celery task, polls for
 *   completion, then fetches a short-lived pre-signed S3 download link.
 * - CSV grades export (sync): triggers a direct browser download.
 * - Both export options are disabled when `hasLockedGrades` is false.
 *
 * Security:
 * - No student essay content is stored in browser storage (localStorage,
 *   sessionStorage, or cookies) at any point in the download flow.
 * - Pre-signed download URL is held only in React component state — not
 *   persisted across page refreshes.
 * - Error messages are static strings; raw server text and student PII are
 *   never rendered.
 */

import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  startExport,
  getExportStatus,
  getExportDownloadUrl,
  downloadGradesCsv,
} from "@/lib/api/exports";
import type { ExportTaskStatus } from "@/lib/api/exports";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Polling interval while an export task is in-progress (milliseconds). */
export const EXPORT_POLL_INTERVAL_MS = 3000;

/** Task statuses that end polling. */
const TERMINAL_EXPORT_STATUSES = new Set<ExportTaskStatus>([
  "complete",
  "failed",
]);

// ---------------------------------------------------------------------------
// Error mapping
// ---------------------------------------------------------------------------

function pdfExportErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to export this assignment.";
      case "NOT_FOUND":
        return "Assignment not found. Please refresh the page.";
      case "NO_LOCKED_GRADES":
        return "No locked grades available for export.";
      default:
        return "Failed to start export. Please try again.";
    }
  }
  return "Failed to start export. Please try again.";
}

function csvExportErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to export grades.";
      case "NOT_FOUND":
        return "Assignment not found. Please refresh the page.";
      case "NO_LOCKED_GRADES":
        return "No locked grades available for export.";
      default:
        return "Failed to download grades. Please try again.";
    }
  }
  return "Failed to download grades. Please try again.";
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ExportPanelProps {
  /** UUID of the assignment to export. */
  assignmentId: string;
  /**
   * Whether at least one grade is locked for this assignment.
   * Both PDF and CSV exports are disabled when this is false.
   */
  hasLockedGrades: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ExportPanel({ assignmentId, hasLockedGrades }: ExportPanelProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Active export task ID — set when a PDF export is started.
  const [taskId, setTaskId] = useState<string | null>(null);
  // Pre-signed download URL — set when the export task completes.
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  const [pdfError, setPdfError] = useState<string | null>(null);
  const [csvError, setCsvError] = useState<string | null>(null);

  // Close the menu when clicking outside
  useEffect(() => {
    if (!menuOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpen]);

  // ----- Export status polling -----
  const {
    data: exportStatus,
    isError: statusFetchError,
  } = useQuery({
    queryKey: ["export-status", taskId],
    queryFn: () => getExportStatus(taskId!),
    enabled: taskId != null,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      if (TERMINAL_EXPORT_STATUSES.has(data.status)) return false;
      return EXPORT_POLL_INTERVAL_MS;
    },
    refetchOnWindowFocus: false,
    staleTime: 0,
    retry: false,
  });

  // ----- Fetch download URL when export completes -----
  const {
    data: downloadData,
    isError: downloadFetchError,
  } = useQuery({
    queryKey: ["export-download", taskId],
    queryFn: () => getExportDownloadUrl(taskId!),
    enabled: taskId != null && exportStatus?.status === "complete",
    // The URL is short-lived; do not re-use a cached value.
    staleTime: 0,
    retry: false,
  });

  // Sync the download URL into component state so we can display it.
  // It is intentionally NOT stored in browser storage.
  useEffect(() => {
    if (downloadData?.download_url) {
      setDownloadUrl(downloadData.download_url);
    }
  }, [downloadData]);

  // ----- Start PDF export -----
  const startExportMutation = useMutation({
    mutationFn: () =>
      startExport(assignmentId, { format: "pdf", student_ids: "all" }),
    onSuccess: (data) => {
      setPdfError(null);
      setDownloadUrl(null);
      setTaskId(data.task_id);
    },
    onError: (err: unknown) => {
      setPdfError(pdfExportErrorMessage(err));
    },
  });

  // ----- CSV download -----
  const csvMutation = useMutation({
    mutationFn: () => downloadGradesCsv(assignmentId),
    onSuccess: () => {
      setCsvError(null);
    },
    onError: (err: unknown) => {
      setCsvError(csvExportErrorMessage(err));
    },
  });

  const handleStartPdfExport = () => {
    setPdfError(null);
    setDownloadUrl(null);
    setTaskId(null);
    startExportMutation.mutate();
  };

  const handleCsvExport = () => {
    setCsvError(null);
    csvMutation.mutate();
  };

  // Derived state
  const isExporting =
    startExportMutation.isPending ||
    (taskId != null &&
      exportStatus != null &&
      !TERMINAL_EXPORT_STATUSES.has(exportStatus.status));

  const exportFailed =
    exportStatus?.status === "failed" || statusFetchError || downloadFetchError;

  const pdfDisabled = !hasLockedGrades || isExporting;
  const csvDisabled = !hasLockedGrades || csvMutation.isPending;

  const disabledReason = !hasLockedGrades
    ? "Lock at least one grade to enable export."
    : null;

  return (
    <div className="relative" ref={menuRef}>
      {/* Export trigger button */}
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={menuOpen}
        aria-label="Export options"
        className="flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
      >
        <svg
          aria-hidden="true"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
          />
        </svg>
        Export
        <svg
          aria-hidden="true"
          className="h-3 w-3"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {/* Dropdown menu */}
      {menuOpen && (
        <div
          role="menu"
          aria-label="Export options menu"
          className="absolute right-0 z-10 mt-2 w-72 origin-top-right rounded-lg border border-gray-200 bg-white shadow-lg focus:outline-none"
        >
          <div className="p-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Export
            </p>

            {/* Disabled reason */}
            {disabledReason && (
              <p className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
                {disabledReason}
              </p>
            )}

            {/* PDF ZIP export */}
            <div className="mb-2">
              <button
                type="button"
                role="menuitem"
                disabled={pdfDisabled}
                onClick={handleStartPdfExport}
                aria-label="Export feedback as PDF ZIP"
                className="w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2.5 text-left text-sm font-medium text-gray-700 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="flex items-center gap-2">
                  <svg
                    aria-hidden="true"
                    className="h-4 w-4 shrink-0 text-gray-400"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>
                  <span>
                    <span className="block font-semibold">
                      {startExportMutation.isPending
                        ? "Starting export…"
                        : isExporting
                          ? "Export in progress…"
                          : "Export feedback as PDF ZIP"}
                    </span>
                    <span className="block text-xs text-gray-500">
                      Generates a ZIP of per-student PDF feedback files
                    </span>
                  </span>
                </span>
              </button>

              {/* PDF export progress / status */}
              {isExporting && (
                <div
                  aria-live="polite"
                  className="mt-2 flex items-center gap-2 rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-700"
                >
                  <svg
                    aria-hidden="true"
                    className="h-3.5 w-3.5 animate-spin"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                    />
                  </svg>
                  <span>
                    {exportStatus?.progress != null
                      ? `Exporting… ${exportStatus.progress}%`
                      : "Preparing export…"}
                  </span>
                </div>
              )}

              {exportFailed && !isExporting && (
                <p
                  role="alert"
                  className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700"
                >
                  Export failed. Please try again.
                </p>
              )}

              {pdfError && (
                <p
                  role="alert"
                  className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700"
                >
                  {pdfError}
                </p>
              )}

              {/* Download link — shown once ready */}
              {downloadUrl && exportStatus?.status === "complete" && (
                <a
                  href={downloadUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 flex items-center gap-1.5 rounded-md bg-green-50 px-3 py-2 text-xs font-medium text-green-700 hover:bg-green-100 focus:outline-none focus:ring-2 focus:ring-green-500"
                  aria-label="Download the exported PDF ZIP file"
                >
                  <svg
                    aria-hidden="true"
                    className="h-3.5 w-3.5 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                    />
                  </svg>
                  Download ZIP — ready
                </a>
              )}
            </div>

            {/* Divider */}
            <div className="my-2 border-t border-gray-100" />

            {/* CSV grades export */}
            <button
              type="button"
              role="menuitem"
              disabled={csvDisabled}
              onClick={handleCsvExport}
              aria-label="Export grades as CSV"
              className="w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2.5 text-left text-sm font-medium text-gray-700 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="flex items-center gap-2">
                <svg
                  aria-hidden="true"
                  className="h-4 w-4 shrink-0 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M3 10h18M3 14h18M3 18h18M3 6h18"
                  />
                </svg>
                <span>
                  <span className="block font-semibold">
                    {csvMutation.isPending
                      ? "Downloading…"
                      : "Export grades as CSV"}
                  </span>
                  <span className="block text-xs text-gray-500">
                    All locked grades — compatible with LMS gradebook import
                  </span>
                </span>
              </span>
            </button>

            {csvError && (
              <p
                role="alert"
                className="mt-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700"
              >
                {csvError}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
