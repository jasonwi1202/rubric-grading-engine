"use client";

/**
 * CsvImportDialog — two-phase CSV roster import flow.
 *
 * Phase 1 (upload): teacher selects a CSV file; the file is sent to the
 * server which returns a diff preview (no DB writes).
 *
 * Phase 2 (review): teacher reviews per-row statuses (new / updated /
 * skipped / error) and aggregate counts before committing.  They can cancel
 * at any stage.
 *
 * Security: the file is sent via multipart to the backend; no CSV content
 * is stored in browser storage or logged.
 */

import { useRef, useState } from "react";
import { previewCsvImport, confirmCsvImport } from "@/lib/api/classes";
import type { CsvImportPreviewResponse, CsvImportRow } from "@/lib/api/classes";
import { ApiError } from "@/lib/api/errors";
import { useFocusTrap } from "@/lib/utils/focus-trap";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Pill badge for a CSV row status. */
function StatusBadge({ status }: { status: CsvImportRow["status"] }) {
  const map: Record<CsvImportRow["status"], string> = {
    new: "bg-green-100 text-green-800",
    updated: "bg-blue-100 text-blue-800",
    skipped: "bg-gray-100 text-gray-600",
    error: "bg-red-100 text-red-700",
  };
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize ${map[status]}`}
    >
      {status}
    </span>
  );
}

/** Aggregate diff counts displayed in the review phase. */
interface DiffCounts {
  new: number;
  updated: number;
  skipped: number;
  error: number;
}

/** Summary row showing aggregate counts from the diff. */
export function CsvDiffSummary({ counts }: { counts: DiffCounts }) {
  return (
    <dl
      className="grid grid-cols-4 gap-2 rounded-md bg-gray-50 p-3 text-center text-sm"
      aria-label="Import summary"
    >
      <div>
        <dt className="font-medium text-green-700">New</dt>
        <dd className="text-lg font-bold text-green-700">{counts.new}</dd>
      </div>
      <div>
        <dt className="font-medium text-blue-700">Updated</dt>
        <dd className="text-lg font-bold text-blue-700">{counts.updated}</dd>
      </div>
      <div>
        <dt className="font-medium text-gray-600">Skipped</dt>
        <dd className="text-lg font-bold text-gray-600">{counts.skipped}</dd>
      </div>
      <div>
        <dt className="font-medium text-red-700">Errors</dt>
        <dd className="text-lg font-bold text-red-700">{counts.error}</dd>
      </div>
    </dl>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CsvImportDialogProps {
  classId: string;
  open: boolean;
  onClose: () => void;
  onImported: (result: { created: number; updated: number; skipped: number }) => void;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CsvImportDialog({
  classId,
  open,
  onClose,
  onImported,
}: CsvImportDialogProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [phase, setPhase] = useState<"upload" | "review" | "confirming">(
    "upload",
  );
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<CsvImportPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleClose = () => {
    // Reset all state on close
    setPhase("upload");
    setSelectedFile(null);
    setPreview(null);
    setError(null);
    setIsLoading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
    onClose();
  };

  const { dialogRef, handleKeyDown } = useFocusTrap({ open, onClose: handleClose });

  if (!open) return null;

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setError(null);
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setError("Please select a CSV file.");
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const result = await previewCsvImport(classId, selectedFile);
      setPreview(result);
      setPhase("review");
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setError(
          "Invalid CSV file. Make sure it has a full_name column and fewer than 200 rows.",
        );
      } else {
        setError("Failed to read the CSV file. Please try again.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!preview) return;
    // Send only new/updated rows, mapped to the shape the backend expects.
    const approvedRows = preview.rows
      .filter((r) => r.status === "new" || r.status === "updated")
      .map(
        (r): { row_number: number; full_name: string; external_id: string | null } => ({
          row_number: r.row_number,
          full_name: r.full_name,
          external_id: r.external_id,
        }),
      );
    setPhase("confirming");
    setError(null);
    try {
      const result = await confirmCsvImport(classId, approvedRows);
      handleClose();
      onImported(result);
    } catch {
      setPhase("review");
      setError("Failed to import students. Please try again.");
    }
  };

  // Map flat backend counts to the shape CsvDiffSummary expects
  const diffCounts = preview
    ? {
        new: preview.new_count,
        updated: preview.updated_count,
        skipped: preview.skipped_count,
        error: preview.error_count,
      }
    : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="csv-import-title"
        className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl"
        onKeyDown={handleKeyDown}
      >
        <h2
          id="csv-import-title"
          className="mb-4 text-lg font-semibold text-gray-900"
        >
          {phase === "upload" ? "Import roster from CSV" : "Review import"}
        </h2>

        {/* ---- Phase 1: Upload ---- */}
        {phase === "upload" && (
          <div className="space-y-4">
            <p className="text-sm text-gray-600">
              Upload a CSV file with a <code>full_name</code> column and an
              optional <code>external_id</code> column. Maximum 200 rows.
            </p>

            <div>
              <label
                htmlFor="csv-file"
                className="block text-sm font-medium text-gray-700"
              >
                CSV file <span aria-hidden="true">*</span>
              </label>
              <input
                ref={fileInputRef}
                id="csv-file"
                type="file"
                accept=".csv,text/csv"
                onChange={handleFileChange}
                disabled={isLoading}
                aria-describedby={error ? "csv-error" : undefined}
                className="mt-1 block w-full text-sm text-gray-700 file:mr-3 file:rounded-md file:border-0 file:bg-blue-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-blue-700 hover:file:bg-blue-100 disabled:opacity-50"
              />
            </div>

            {error && (
              <p
                id="csv-error"
                role="alert"
                className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
              >
                {error}
              </p>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleClose}
                disabled={isLoading}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleUpload}
                disabled={isLoading || !selectedFile}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
              >
                {isLoading ? "Reading file…" : "Preview import"}
              </button>
            </div>
          </div>
        )}

        {/* ---- Phase 2: Review diff ---- */}
        {(phase === "review" || phase === "confirming") && preview && diffCounts && (
          <div className="space-y-4">
            <CsvDiffSummary counts={diffCounts} />

            <div
              className="max-h-64 overflow-y-auto rounded-md border border-gray-200"
              aria-label="Import row details"
            >
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-gray-50 text-xs font-medium uppercase text-gray-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Row</th>
                    <th className="px-3 py-2 text-left">Name</th>
                    <th className="px-3 py-2 text-left">External ID</th>
                    <th className="px-3 py-2 text-left">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {preview.rows.map((row) => (
                    <tr key={row.row_number} className="bg-white">
                      <td className="px-3 py-2 text-gray-500">
                        {row.row_number}
                      </td>
                      <td className="px-3 py-2 font-medium text-gray-900">
                        {row.full_name || (
                          <span className="italic text-gray-400">(empty)</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-gray-600">
                        {row.external_id ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge status={row.status} />
                        {row.message && (
                          <span className="ml-2 text-xs text-gray-500">
                            {row.message}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {preview.new_count === 0 && preview.updated_count === 0 && (
              <p className="text-sm text-gray-600">
                No new students to import — all rows are already enrolled or
                have errors.
              </p>
            )}

            {error && (
              <p
                role="alert"
                className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
              >
                {error}
              </p>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={handleClose}
                disabled={phase === "confirming"}
                className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={
                  phase === "confirming" ||
                  (preview.new_count === 0 && preview.updated_count === 0)
                }
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
              >
                {phase === "confirming"
                  ? "Importing…"
                  : `Confirm import (${preview.new_count + preview.updated_count})`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

