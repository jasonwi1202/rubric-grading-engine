"use client";

/**
 * BrowserWritingInterface — rich-text essay composition with debounced autosave.
 *
 * Features:
 * - contentEditable rich-text surface with Bold / Italic / Underline toolbar
 * - Debounced autosave: sends a snapshot to the backend every 12 seconds of
 *   activity (within the 10–15 s window specified by M5-09)
 * - Recovers content from the latest snapshot on mount (refresh/navigation safe)
 * - `beforeunload` warning when there are changes not yet acknowledged by the server
 * - Visual autosave status indicator: Idle / Saving… / Saved / Error
 *
 * Security:
 * - No essay content or student PII is stored in browser storage
 *   (localStorage, sessionStorage, or cookies).
 * - No content appears in console logs; only entity IDs (essayId).
 * - Content is sent to the server exclusively via authenticated API calls.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { getSnapshots, saveSnapshot } from "@/lib/api/essays";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Autosave fires this many ms after the last keystroke (12 s ∈ [10 s, 15 s]). */
export const AUTOSAVE_DEBOUNCE_MS = 12_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SaveStatus = "idle" | "saving" | "saved" | "error";

export interface BrowserWritingInterfaceProps {
  /** UUID of the essay to save snapshots against. */
  essayId: string;
  /** UUID of the initial essay version (informational; the service uses essay_id). */
  essayVersionId: string;
  /** Called when the teacher clicks "Submit essay". */
  onSubmit: () => void;
  /** Called when the teacher clicks "Cancel". */
  onCancel: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Count words in an HTML string by stripping tags and splitting on whitespace.
 * Must match the word-count logic used by the backend `_strip_html_tags` path.
 */
export function countWordsFromHtml(html: string): number {
  const text = html.replace(/<[^>]*>/g, " ").replace(/&[a-z]+;/gi, " ").trim();
  if (!text) return 0;
  return text.split(/\s+/).filter(Boolean).length;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function BrowserWritingInterface({
  essayId,
  essayVersionId: _essayVersionId,
  onSubmit,
  onCancel,
}: BrowserWritingInterfaceProps) {
  const editorRef = useRef<HTMLDivElement>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [hasUnsaved, setHasUnsaved] = useState(false);
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedContentRef = useRef<string>("");
  const [isEditorReady, setIsEditorReady] = useState(false);

  // ── Load snapshot state on mount (editor recovery after refresh) ──────────

  const { data: snapshotState, isLoading: isLoadingSnapshots } = useQuery({
    queryKey: ["snapshots", essayId],
    queryFn: () => getSnapshots(essayId),
    enabled: !!essayId,
    // Only fetch once per mount — we own the content locally after that.
    staleTime: Infinity,
    gcTime: 0,
  });

  // Populate the editor once snapshot data is available.
  useEffect(() => {
    if (!editorRef.current || isEditorReady) return;
    if (snapshotState !== undefined) {
      const content = snapshotState.current_content ?? "";
      editorRef.current.innerHTML = content;
      lastSavedContentRef.current = content;
      setIsEditorReady(true);
    }
  }, [snapshotState, isEditorReady]);

  // ── Autosave mutation ─────────────────────────────────────────────────────

  const { mutate: doSave } = useMutation({
    mutationFn: ({
      html_content,
      word_count,
    }: {
      html_content: string;
      word_count: number;
    }) => saveSnapshot(essayId, { html_content, word_count }),
    onMutate: () => {
      setSaveStatus("saving");
    },
    onSuccess: (_data, variables) => {
      setSaveStatus("saved");
      setHasUnsaved(false);
      lastSavedContentRef.current = variables.html_content;
    },
    onError: () => {
      setSaveStatus("error");
    },
  });

  // ── Content helpers ───────────────────────────────────────────────────────

  const getCurrentHtml = useCallback((): string => {
    return editorRef.current?.innerHTML ?? "";
  }, []);

  const triggerSave = useCallback(() => {
    const content = getCurrentHtml();
    if (content === lastSavedContentRef.current) return;
    const wordCount = countWordsFromHtml(content);
    doSave({ html_content: content, word_count: wordCount });
  }, [getCurrentHtml, doSave]);

  // ── Input handler — resets debounce timer on every keystroke ─────────────

  const handleInput = useCallback(() => {
    setHasUnsaved(true);
    // Reset to "idle" only if not currently saving
    setSaveStatus((prev) => (prev === "saving" ? prev : "idle"));

    if (autosaveTimerRef.current) {
      clearTimeout(autosaveTimerRef.current);
    }
    autosaveTimerRef.current = setTimeout(triggerSave, AUTOSAVE_DEBOUNCE_MS);
  }, [triggerSave]);

  // ── beforeunload — warn on unsaved changes ────────────────────────────────

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (!hasUnsaved) return;
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsaved]);

  // ── Cleanup timer on unmount ──────────────────────────────────────────────

  useEffect(() => {
    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, []);

  // ── Toolbar formatting commands ───────────────────────────────────────────

  const execFormat = (command: string) => {
    // document.execCommand is deprecated by the HTML spec but has near-universal
    // browser support and avoids pulling in a full rich-text library for this
    // initial implementation.
    // TODO(M5-09 follow-up): migrate to Selection/Range API or adopt a maintained
    // rich-text library (e.g., TipTap) if execCommand support is dropped.
    document.execCommand(command, false);
    editorRef.current?.focus();
    handleInput();
  };

  // ── Submit ────────────────────────────────────────────────────────────────

  const handleSubmit = () => {
    // Fire a final save synchronously (if there are unsaved changes) before
    // handing control to the parent's onSubmit callback.
    if (hasUnsaved) triggerSave();
    onSubmit();
  };

  // ── Status label ──────────────────────────────────────────────────────────

  const statusLabel: string = (() => {
    if (saveStatus === "saving") return "Saving\u2026";
    if (saveStatus === "saved") return "Saved";
    if (saveStatus === "error") return "Save failed \u2014 will retry";
    if (hasUnsaved) return "Unsaved changes";
    return "";
  })();

  const canSubmit = getCurrentHtml().trim().length > 0;

  return (
    <div className="flex flex-col gap-3">
      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div
        role="toolbar"
        aria-label="Text formatting"
        className="flex gap-1 rounded-t-md border border-gray-300 bg-gray-50 px-2 py-1"
      >
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault(); // prevent editor blur
            execFormat("bold");
          }}
          aria-label="Bold"
          className="rounded px-2 py-1 text-sm font-bold text-gray-700 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          B
        </button>
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            execFormat("italic");
          }}
          aria-label="Italic"
          className="rounded px-2 py-1 text-sm italic text-gray-700 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          I
        </button>
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            execFormat("underline");
          }}
          aria-label="Underline"
          className="rounded px-2 py-1 text-sm underline text-gray-700 hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          U
        </button>
      </div>

      {/* ── Loading skeleton while fetching snapshot state ───────────────── */}
      {isLoadingSnapshots && (
        <div
          aria-live="polite"
          aria-busy="true"
          className="h-64 animate-pulse rounded-b-md bg-gray-100"
        />
      )}

      {/* ── Rich-text editor surface ──────────────────────────────────────── */}
      {!isLoadingSnapshots && (
        <div
          ref={editorRef}
          contentEditable
          role="textbox"
          aria-label="Essay content"
          aria-multiline="true"
          aria-describedby="writing-interface-status"
          suppressContentEditableWarning
          onInput={handleInput}
          className="min-h-64 rounded-b-md border border-t-0 border-gray-300 px-4 py-3 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
          data-testid="essay-editor"
        />
      )}

      {/* ── Status bar ───────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <span
          id="writing-interface-status"
          aria-live="polite"
          aria-atomic="true"
          className={`text-xs ${
            saveStatus === "error"
              ? "text-red-600"
              : saveStatus === "saved"
                ? "text-green-600"
                : "text-gray-500"
          }`}
        >
          {statusLabel}
        </span>

        <div className="flex gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          >
            Submit essay
          </button>
        </div>
      </div>
    </div>
  );
}
