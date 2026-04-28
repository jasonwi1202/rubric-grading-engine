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
 * Count words in an HTML string by stripping tags, decoding HTML entities,
 * normalising whitespace, and splitting on whitespace.
 *
 * Uses `DOMParser` with `text/html` to decode entities and extract plain text
 * safely (no script execution), matching the backend's `_strip_html_tags` path
 * which calls `html.unescape`.
 */
export function countWordsFromHtml(html: string): number {
  // First strip tags via regex to obtain a plain-text-ish string, then use
  // DOMParser to decode any remaining HTML entities accurately.
  const withoutTags = html.replace(/<[^>]*>/g, " ");
  const doc = new DOMParser().parseFromString(withoutTags, "text/html");
  // textContent gives the decoded text without any markup.
  const rawText = doc.body.textContent ?? "";
  // Normalise whitespace (including non-breaking spaces) and trim.
  const normalizedText = rawText.replace(/\u00A0/g, " ").replace(/\s+/g, " ").trim();
  if (!normalizedText) return 0;
  return normalizedText.split(" ").filter(Boolean).length;
}

/**
 * Sanitize HTML from the server before injecting it into the editor's
 * `innerHTML`, preventing stored-XSS from persisted snapshot content.
 *
 * Removes `<script>`, `<style>`, `<link>`, `<iframe>`, `<form>`, and other
 * dangerous elements, and strips all `on*` event-handler attributes and
 * `javascript:` URLs from the remaining elements.
 *
 * Uses `<template>` so no scripts are parsed or executed during processing.
 */
function sanitizeEditorHtml(html: string): string {
  const template = document.createElement("template");
  template.innerHTML = html;
  // Remove dangerous or external-resource-loading elements entirely.
  // img is excluded because pasted images load external URLs in the teacher's browser
  // and introduce uncontrolled content into what is essentially a plain-text essay surface.
  template.content
    .querySelectorAll(
      "script,style,link,meta,iframe,object,embed,form,input,button,textarea,select,svg,img",
    )
    .forEach((el) => el.remove());
  // Strip event-handler attributes and javascript: URLs from remaining nodes.
  template.content.querySelectorAll("*").forEach((el) => {
    for (const attr of Array.from(el.attributes)) {
      if (
        attr.name.startsWith("on") ||
        (["href", "src", "action", "data"].includes(attr.name) &&
          /^javascript:/i.test(attr.value))
      ) {
        el.removeAttribute(attr.name);
      }
    }
  });
  return template.innerHTML;
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
  // Holds sanitized content that arrived while a save was in flight, so it can
  // be flushed in onSettled once the current request completes.
  const pendingContentRef = useRef<string | null>(null);
  // Forward-reference to the stable mutate function, used inside onSettled to
  // schedule a follow-up save without creating a circular useMutation dependency.
  const saveMutationRef = useRef<
    ((vars: { html_content: string; word_count: number }) => void) | null
  >(null);

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
      // Sanitize recovered HTML before injecting to prevent stored-XSS.
      editorRef.current.innerHTML = sanitizeEditorHtml(content);
      lastSavedContentRef.current = content;
      setIsEditorReady(true);
    }
  }, [snapshotState, isEditorReady]);

  // ── Autosave mutation ─────────────────────────────────────────────────────

  const {
    mutate: doSave,
    mutateAsync: doSaveAsync,
    isPending: isSaving,
  } = useMutation({
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
      lastSavedContentRef.current = variables.html_content;
      // Clear the unsaved flag only if no new content arrived during the save.
      // If pendingContentRef is set, onSettled will schedule a follow-up save
      // and hasUnsaved should remain true until that save completes.
      setHasUnsaved(pendingContentRef.current !== null);
    },
    onError: () => {
      setSaveStatus("error");
    },
    onSettled: () => {
      // If new content arrived while the previous save was in flight, save it now.
      const pending = pendingContentRef.current;
      if (pending !== null && pending !== lastSavedContentRef.current) {
        pendingContentRef.current = null;
        const wordCount = countWordsFromHtml(pending);
        saveMutationRef.current?.({ html_content: pending, word_count: wordCount });
      } else {
        pendingContentRef.current = null;
      }
    },
  });
  // Keep forward-ref in sync on every render (doSave is stable across renders).
  saveMutationRef.current = doSave;

  // ── Content helpers ───────────────────────────────────────────────────────

  const getCurrentHtml = useCallback((): string => {
    return editorRef.current?.innerHTML ?? "";
  }, []);

  const triggerSave = useCallback(() => {
    // Sanitize the raw editor HTML before computing word count or sending to the
    // backend. This ensures what the user sees and what is persisted are the same.
    const content = sanitizeEditorHtml(getCurrentHtml());
    if (content === lastSavedContentRef.current) {
      pendingContentRef.current = null;
      return;
    }
    if (isSaving) {
      // A save is in flight — queue the latest content so onSettled can flush it.
      pendingContentRef.current = content;
      return;
    }
    pendingContentRef.current = null;
    const wordCount = countWordsFromHtml(content);
    doSave({ html_content: content, word_count: wordCount });
  }, [getCurrentHtml, doSave, isSaving]);

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
      // Both preventDefault() and setting returnValue are needed for broad
      // browser compatibility — modern Chrome/Firefox require returnValue.
      e.preventDefault();
      e.returnValue = "";
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

  const handleSubmit = useCallback(async () => {
    // Clear any pending debounce timer so we don't duplicate the final save.
    if (autosaveTimerRef.current) {
      clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    pendingContentRef.current = null; // cancel any queued follow-up save
    // Sanitize and await a final save for any unsaved changes before handing off
    // to the parent's onSubmit callback (which may navigate away immediately).
    const content = sanitizeEditorHtml(getCurrentHtml());
    const wordCount = countWordsFromHtml(content);
    if (content !== lastSavedContentRef.current && wordCount > 0) {
      try {
        await doSaveAsync({ html_content: content, word_count: wordCount });
      } catch {
        // If the final save fails, still allow the submission to proceed.
      }
    }
    onSubmit();
  }, [getCurrentHtml, doSaveAsync, onSubmit]);

  // ── Status label ──────────────────────────────────────────────────────────

  const statusLabel: string = (() => {
    if (saveStatus === "saving") return "Saving\u2026";
    if (saveStatus === "saved") return "Saved";
    if (saveStatus === "error") return "Save failed";
    if (hasUnsaved) return "Unsaved changes";
    return "";
  })();

  // Use textContent (not innerHTML) so markup-only states like <br>/<div><br></div>
  // don't incorrectly enable submission of an effectively-empty essay.
  const canSubmit = (editorRef.current?.textContent?.trim().length ?? 0) > 0;

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
