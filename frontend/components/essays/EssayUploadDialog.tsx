"use client";

/**
 * EssayUploadDialog — multi-file drag-and-drop upload + text-paste input.
 *
 * Supports:
 * - Drag-and-drop or click-to-browse for one or more PDF/DOCX/TXT files.
 * - Text-paste tab: teacher can type or paste essay text directly.
 * - Per-file and overall upload progress indicator.
 * - Client-side Zod validation: file type and size before any network call.
 *
 * Security:
 * - File names and content never appear in error messages or logs.
 * - Validation errors reference generic file type/size limits only.
 * - No essay content is stored in browser storage.
 */

import { useRef, useState } from "react";
import { z } from "zod";
import { uploadEssays } from "@/lib/api/essays";
import type { EssayUploadResult } from "@/lib/api/essays";
import { ApiError } from "@/lib/api/errors";
import { useFocusTrap } from "@/lib/utils/focus-trap";

// ---------------------------------------------------------------------------
// Constants & validation
// ---------------------------------------------------------------------------

const MAX_FILE_SIZE_MB = 10;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

const MAX_TEXT_LENGTH = 500_000;

const ALLOWED_MIME_TYPES = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
]);

const ALLOWED_EXTENSIONS = new Set([".pdf", ".docx", ".txt"]);

/** Zod schema for a single uploaded file. */
export const fileSchema = z
  .instanceof(File)
  .refine(
    (f) => {
      // Files without a dot (no extension) can only be validated by MIME type.
      const dotIndex = f.name.lastIndexOf(".");
      const ext = dotIndex >= 0 ? f.name.slice(dotIndex).toLowerCase() : "";
      return (
        ALLOWED_MIME_TYPES.has(f.type) || (ext !== "" && ALLOWED_EXTENSIONS.has(ext))
      );
    },
    { message: "Only PDF, DOCX, and TXT files are allowed." },
  )
  .refine((f) => f.size <= MAX_FILE_SIZE_BYTES, {
    message: `File exceeds the ${MAX_FILE_SIZE_MB} MB limit.`,
  });

/** Zod schema for the text-paste form. */
export const pasteTextSchema = z.object({
  text: z
    .string()
    .trim()
    .min(1, "Essay text is required.")
    .max(MAX_TEXT_LENGTH, `Essay text is too long (max ${MAX_TEXT_LENGTH.toLocaleString()} characters).`),
});

// ---------------------------------------------------------------------------
// Tab type
// ---------------------------------------------------------------------------

type InputTab = "file" | "text";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface EssayUploadDialogProps {
  assignmentId: string;
  open: boolean;
  onClose: () => void;
  /** Called after a successful upload with the server-returned results. */
  onUploaded: (results: EssayUploadResult[]) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EssayUploadDialog({
  assignmentId,
  open,
  onClose,
  onUploaded,
}: EssayUploadDialogProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);

  const [activeTab, setActiveTab] = useState<InputTab>("file");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [pasteText, setPasteText] = useState("");
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState(0); // 0-100

  const handleClose = () => {
    setActiveTab("file");
    setSelectedFiles([]);
    setPasteText("");
    setValidationErrors([]);
    setUploadError(null);
    setIsDragging(false);
    setIsUploading(false);
    setProgress(0);
    if (fileInputRef.current) fileInputRef.current.value = "";
    onClose();
  };

  const { dialogRef, handleKeyDown } = useFocusTrap({
    open,
    onClose: handleClose,
  });

  if (!open) return null;

  // ── File validation helper ────────────────────────────────────────────────

  function validateFiles(files: File[]): { valid: File[]; errors: string[] } {
    const valid: File[] = [];
    const errors: string[] = [];
    for (const file of files) {
      const result = fileSchema.safeParse(file);
      if (result.success) {
        valid.push(file);
      } else {
        // Use generic message without file name to avoid leaking PII/paths
        errors.push(result.error.issues[0]?.message ?? "Invalid file.");
      }
    }
    return { valid, errors };
  }

  // ── Drag-and-drop handlers ────────────────────────────────────────────────

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    const dropZone = dropZoneRef.current;
    const relatedTarget = e.relatedTarget;
    if (!dropZone || !(relatedTarget instanceof Node) || !dropZone.contains(relatedTarget)) {
      setIsDragging(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = Array.from(e.dataTransfer.files);
    addFiles(dropped);
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = Array.from(e.target.files ?? []);
    addFiles(chosen);
  };

  function addFiles(incoming: File[]) {
    const { valid, errors } = validateFiles(incoming);
    setValidationErrors(errors);
    setUploadError(null);
    setSelectedFiles((prev) => {
      // Deduplicate by name+size
      const existing = new Set(prev.map((f) => `${f.name}:${f.size}`));
      const newOnes = valid.filter(
        (f) => !existing.has(`${f.name}:${f.size}`),
      );
      return [...prev, ...newOnes];
    });
  }

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // ── Upload ────────────────────────────────────────────────────────────────

  const handleUpload = async () => {
    setUploadError(null);
    setValidationErrors([]);

    if (activeTab === "file") {
      if (selectedFiles.length === 0) {
        setValidationErrors(["Please add at least one file."]);
        return;
      }
    } else {
      const parsed = pasteTextSchema.safeParse({ text: pasteText });
      if (!parsed.success) {
        setValidationErrors(
          parsed.error.issues.map((issue) => issue.message),
        );
        return;
      }
    }

    setIsUploading(true);
    setProgress(10); // show immediate feedback

    let ticker: ReturnType<typeof setInterval> | null = null;
    try {
      // Simulate incremental progress during upload (genuine XHR progress
      // requires XMLHttpRequest; fetch has no progress events).
      ticker = setInterval(() => {
        setProgress((p) => Math.min(p + 10, 90));
      }, 300);

      const results = await uploadEssays(assignmentId, {
        files: activeTab === "file" ? selectedFiles : undefined,
        text: activeTab === "text" ? pasteText.trim() : undefined,
      });

      setProgress(100);

      // Short delay so the teacher sees 100% before the dialog closes.
      await new Promise((r) => setTimeout(r, 400));

      handleClose();
      onUploaded(results);
    } catch (err) {
      setProgress(0);
      if (err instanceof ApiError) {
        const code = err.code;
        if (code === "FILE_TYPE_NOT_ALLOWED") {
          setUploadError("One or more files have an unsupported type. Use PDF, DOCX, or TXT.");
        } else if (code === "FILE_TOO_LARGE") {
          setUploadError(`One or more files exceed the ${MAX_FILE_SIZE_MB} MB limit.`);
        } else {
          setUploadError("Upload failed. Please try again.");
        }
      } else {
        setUploadError("Upload failed. Please try again.");
      }
    } finally {
      if (ticker !== null) clearInterval(ticker);
      setIsUploading(false);
    }
  };

  // ── Derived state ─────────────────────────────────────────────────────────

  const hasErrors = validationErrors.length > 0 || uploadError !== null;
  const canSubmit =
    !isUploading &&
    (activeTab === "file" ? selectedFiles.length > 0 : pasteText.trim().length > 0);

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
        aria-labelledby="essay-upload-title"
        className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl"
        onKeyDown={handleKeyDown}
        tabIndex={-1}
      >
        <h2
          id="essay-upload-title"
          className="mb-4 text-lg font-semibold text-gray-900"
        >
          Upload essays
        </h2>

        {/* ── Tabs ──────────────────────────────────────────────────────── */}
        <div
          role="tablist"
          aria-label="Input method"
          className="mb-4 flex gap-2 border-b border-gray-200"
        >
          <button
            role="tab"
            aria-selected={activeTab === "file"}
            aria-controls="tab-panel-file"
            id="tab-file"
            type="button"
            disabled={isUploading}
            onClick={() => {
              setActiveTab("file");
              setValidationErrors([]);
              setUploadError(null);
            }}
            className={`px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              activeTab === "file"
                ? "border-b-2 border-blue-600 text-blue-700"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            File upload
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "text"}
            aria-controls="tab-panel-text"
            id="tab-text"
            type="button"
            disabled={isUploading}
            onClick={() => {
              setActiveTab("text");
              setValidationErrors([]);
              setUploadError(null);
            }}
            className={`px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              activeTab === "text"
                ? "border-b-2 border-blue-600 text-blue-700"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Paste text
          </button>
        </div>

        {/* ── File upload tab ───────────────────────────────────────────── */}
        <div
          role="tabpanel"
          id="tab-panel-file"
          aria-labelledby="tab-file"
          hidden={activeTab !== "file"}
        >
          <div className="space-y-4">
            {/* Drop zone */}
            <div
              ref={dropZoneRef}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => !isUploading && fileInputRef.current?.click()}
              role="button"
              tabIndex={isUploading ? -1 : 0}
              aria-label="Drop zone: drag and drop essay files here, or press Enter to browse"
              onKeyDown={(e) => {
                if ((e.key === "Enter" || e.key === " ") && !isUploading) {
                  fileInputRef.current?.click();
                }
              }}
              className={`flex min-h-[128px] cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-6 transition-colors ${
                isDragging
                  ? "border-blue-500 bg-blue-50"
                  : "border-gray-300 bg-gray-50 hover:border-blue-400 hover:bg-blue-50"
              } ${isUploading ? "cursor-not-allowed opacity-50" : ""}`}
            >
              <svg
                className="mb-2 h-8 w-8 text-gray-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
                />
              </svg>
              <p className="text-sm text-gray-600">
                Drag &amp; drop files here, or{" "}
                <span className="font-medium text-blue-600">browse</span>
              </p>
              <p className="mt-1 text-xs text-gray-400">
                PDF, DOCX, TXT · max {MAX_FILE_SIZE_MB} MB each
              </p>
            </div>

            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              id="essay-file-input"
              type="file"
              multiple
              accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              className="sr-only"
              aria-label="Select essay files"
              onChange={handleFileInputChange}
              disabled={isUploading}
            />

            {/* Selected files list */}
            {selectedFiles.length > 0 && (
              <ul
                aria-label="Selected files"
                className="space-y-1"
              >
                {selectedFiles.map((file, idx) => (
                  <li
                    key={`${file.name}-${idx}`}
                    className="flex items-center justify-between rounded-md bg-gray-50 px-3 py-1.5 text-sm"
                  >
                    <span className="truncate text-gray-700">
                      {file.name}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeFile(idx)}
                      disabled={isUploading}
                      aria-label={`Remove ${file.name}`}
                      className="ml-2 flex-shrink-0 text-gray-400 hover:text-red-600 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:opacity-50"
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* ── Text paste tab ────────────────────────────────────────────── */}
        <div
          role="tabpanel"
          id="tab-panel-text"
          aria-labelledby="tab-text"
          hidden={activeTab !== "text"}
        >
          <div className="space-y-2">
            <label
              htmlFor="essay-paste-text"
              className="block text-sm font-medium text-gray-700"
            >
              Essay text <span aria-hidden="true">*</span>
            </label>
            <textarea
              id="essay-paste-text"
              value={pasteText}
              onChange={(e) => {
                setPasteText(e.target.value);
                setValidationErrors([]);
                setUploadError(null);
              }}
              disabled={isUploading}
              rows={8}
              placeholder="Paste or type essay text here…"
              aria-describedby={hasErrors ? "essay-upload-errors" : undefined}
              className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            />
            <p className="text-right text-xs text-gray-400">
              {pasteText.length.toLocaleString()} / {MAX_TEXT_LENGTH.toLocaleString()}
            </p>
          </div>
        </div>

        {/* ── Progress bar ──────────────────────────────────────────────── */}
        {isUploading && (
          <div className="mt-4">
            <progress
              value={progress}
              max={100}
              aria-label="Upload progress"
              className="h-2 w-full accent-blue-600"
            />
            <p className="mt-1 text-center text-xs text-gray-500">
              Uploading… {progress}%
            </p>
          </div>
        )}

        {/* ── Errors ───────────────────────────────────────────────────── */}
        {hasErrors && (
          <ul
            id="essay-upload-errors"
            role="alert"
            aria-live="polite"
            className="mt-3 space-y-1 rounded-md bg-red-50 px-3 py-2"
          >
            {validationErrors.map((msg, i) => (
              <li key={i} className="text-sm text-red-700">
                {msg}
              </li>
            ))}
            {uploadError && (
              <li className="text-sm text-red-700">{uploadError}</li>
            )}
          </ul>
        )}

        {/* ── Actions ──────────────────────────────────────────────────── */}
        <div className="mt-4 flex justify-end gap-3">
          <button
            type="button"
            onClick={handleClose}
            disabled={isUploading}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleUpload}
            disabled={!canSubmit}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          >
            {isUploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
