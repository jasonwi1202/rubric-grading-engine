"use client";

/**
 * TextCommentBankPicker — text comment bank picker for EssayReviewPanel.
 *
 * Features:
 * - "Text comment bank" toggle button opens/closes the picker panel.
 * - "Save to bank" button saves the current feedback text as a reusable snippet.
 * - Search input fetches fuzzy-match suggestions from GET /comment-bank/suggestions.
 * - When the search input is empty, all saved comments are listed.
 * - Each entry has an "Apply" button that replaces the linked textarea's content
 *   without losing the original text (it becomes the new controlled value so the
 *   teacher can still edit before blur-save).
 * - All controls are disabled when the grade is locked; a read-only notice is shown.
 *
 * Security:
 * - No student PII in any log or error path.
 * - Error messages are static strings; raw server text is never shown.
 * - Entity IDs only in error payloads.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCommentBankEntry,
  deleteCommentBankEntry,
  getCommentBankSuggestions,
  listCommentBank,
} from "@/lib/api/comment-bank";
import type {
  CommentBankEntry,
  CommentBankSuggestion,
} from "@/lib/api/comment-bank";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Error message helpers — static strings only, never raw server messages
// ---------------------------------------------------------------------------

function saveErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to save to the comment bank.";
      case "VALIDATION_ERROR":
        return "Comment text is too long or empty. Please check and try again.";
      default:
        return "Failed to save comment. Please try again.";
    }
  }
  return "Failed to save comment. Please try again.";
}

function applyErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "NOT_FOUND":
        return "Comment not found. It may have been deleted.";
      default:
        return "Failed to apply comment. Please try again.";
    }
  }
  return "Failed to apply comment. Please try again.";
}

function deleteErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to delete this comment.";
      case "NOT_FOUND":
        return "Comment not found. It may have already been deleted.";
      default:
        return "Failed to delete comment. Please try again.";
    }
  }
  return "Failed to delete comment. Please try again.";
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TextCommentBankPickerProps {
  /**
   * The current text from the linked feedback field.
   * Used as the default value for the "Save to bank" operation.
   */
  currentText: string;
  /**
   * Called when the teacher applies a banked comment.
   * The parent component should update the controlled input value.
   */
  onApply: (text: string) => void;
  /**
   * When true, all save and apply controls are disabled and a read-only
   * notice is shown.
   */
  isLocked: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TextCommentBankPicker({
  currentText,
  onApply,
  isLocked,
}: TextCommentBankPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [appliedId, setAppliedId] = useState<string | null>(null);
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const appliedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryClient = useQueryClient();

  // Clean up pending timers on unmount.
  useEffect(() => {
    return () => {
      if (savedTimerRef.current !== null) clearTimeout(savedTimerRef.current);
      if (appliedTimerRef.current !== null)
        clearTimeout(appliedTimerRef.current);
    };
  }, []);

  // ---- Queries ----

  // Full list — fetched when picker opens and search is empty.
  const {
    data: allComments,
    isLoading: isListLoading,
    isError: isListError,
  } = useQuery({
    queryKey: ["comment-bank"],
    queryFn: listCommentBank,
    enabled: isOpen,
    staleTime: 30_000,
  });

  // Suggestions — fetched when search query is non-empty.
  const trimmedQuery = searchQuery.trim();
  const {
    data: suggestions,
    isLoading: isSuggestLoading,
    isError: isSuggestError,
  } = useQuery({
    queryKey: ["comment-bank-suggestions", trimmedQuery],
    queryFn: () => getCommentBankSuggestions(trimmedQuery),
    enabled: isOpen && trimmedQuery.length > 0,
    staleTime: 10_000,
  });

  // Derive the displayed list:
  // - Non-empty search → show suggestions (or loading/error)
  // - Empty search → show full list
  const isSearching = trimmedQuery.length > 0;
  const isLoading = isSearching ? isSuggestLoading : isListLoading;
  const isError = isSearching ? isSuggestError : isListError;
  const displayedItems: (CommentBankEntry | CommentBankSuggestion)[] =
    isSearching ? (suggestions ?? []) : (allComments ?? []);
  const isEmpty = !isLoading && !isError && displayedItems.length === 0;

  // ---- Save to bank ----
  const saveMutation = useMutation({
    mutationFn: () => createCommentBankEntry(currentText.trim()),
    onSuccess: (entry) => {
      setSaveError(null);
      setSavedId(entry.id);
      void queryClient.invalidateQueries({ queryKey: ["comment-bank"] });
      if (savedTimerRef.current !== null) clearTimeout(savedTimerRef.current);
      savedTimerRef.current = setTimeout(() => {
        setSavedId(null);
        savedTimerRef.current = null;
      }, 2000);
    },
    onError: (err: unknown) => {
      setSaveError(saveErrorMessage(err));
    },
  });

  // ---- Apply from bank ----
  const handleApply = useCallback(
    (text: string, id: string) => {
      if (isLocked) return;
      onApply(text);
      setApplyError(null);
      setAppliedId(id);
      if (appliedTimerRef.current !== null)
        clearTimeout(appliedTimerRef.current);
      appliedTimerRef.current = setTimeout(() => {
        setAppliedId(null);
        appliedTimerRef.current = null;
      }, 2000);
    },
    [isLocked, onApply],
  );

  // ---- Delete from bank ----
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteCommentBankEntry(id),
    onSuccess: (_data, id) => {
      setDeleteError(null);
      void queryClient.invalidateQueries({ queryKey: ["comment-bank"] });
      void queryClient.invalidateQueries({
        queryKey: ["comment-bank-suggestions"],
      });
      // Clear applied indicator if the deleted entry was just applied.
      if (appliedId === id) setAppliedId(null);
    },
    onError: (err: unknown) => {
      setDeleteError(deleteErrorMessage(err));
    },
  });

  const canSave = !isLocked && currentText.trim().length > 0;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        aria-expanded={isOpen}
        aria-controls="text-bank-picker-panel"
        className="flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
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
            d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
          />
        </svg>
        {isOpen ? "Hide text comment bank" : "Text comment bank"}
      </button>

      {isOpen && (
        <div
          id="text-bank-picker-panel"
          className="mt-2 rounded-md border border-gray-200 bg-gray-50 p-3"
          role="region"
          aria-label="Text comment bank"
        >
          {/* Locked notice */}
          {isLocked && (
            <p
              className="mb-3 rounded-md bg-yellow-50 px-3 py-2 text-xs text-yellow-800"
            >
              This grade is locked. Save and apply controls are disabled.
            </p>
          )}

          {/* Save current text to bank */}
          <div className="mb-3 flex items-center gap-2">
            <button
              type="button"
              disabled={!canSave || saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
              aria-label="Save current feedback text to comment bank"
              className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saveMutation.isPending
                ? "Saving…"
                : savedId
                  ? "Saved!"
                  : "Save to bank"}
            </button>
            {isLocked && (
              <span className="text-xs text-gray-500">
                Grade is locked — read only.
              </span>
            )}
          </div>

          {saveError && (
            <p role="alert" className="mb-3 text-xs text-red-700">
              {saveError}
            </p>
          )}

          {deleteError && (
            <p role="alert" className="mb-3 text-xs text-red-700">
              {deleteError}
            </p>
          )}

          {applyError && (
            <p role="alert" className="mb-3 text-xs text-red-700">
              {applyError}
            </p>
          )}

          {/* Search */}
          <div className="mb-3">
            <label
              htmlFor="text-bank-search"
              className="mb-1 block text-xs font-medium text-gray-700"
            >
              Search saved comments
            </label>
            <input
              id="text-bank-search"
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Type to search…"
              aria-label="Search saved comments"
              className="w-full rounded-md border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Loading */}
          {isLoading && (
            <p className="text-xs text-gray-500" aria-live="polite">
              {isSearching ? "Searching…" : "Loading saved comments…"}
            </p>
          )}

          {/* Error */}
          {isError && (
            <p className="text-xs text-red-600" role="alert">
              Failed to load saved comments. Please try again.
            </p>
          )}

          {/* Empty state */}
          {isEmpty && (
            <p className="text-xs text-gray-500">
              {isSearching
                ? "No matching comments found."
                : "No saved comments yet. Add feedback and click \u201cSave to bank\u201d."}
            </p>
          )}

          {/* Comment list */}
          {displayedItems.length > 0 && (
            <ul className="space-y-2" aria-label="Saved text comments">
              {displayedItems.map((item) => (
                <BankEntryRow
                  key={item.id}
                  entry={item}
                  isLocked={isLocked}
                  isApplied={appliedId === item.id}
                  isDeleting={deleteMutation.isPending}
                  onApply={() => handleApply(item.text, item.id)}
                  onDelete={() => deleteMutation.mutate(item.id)}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// BankEntryRow — individual entry in the picker list
// ---------------------------------------------------------------------------

interface BankEntryRowProps {
  entry: CommentBankEntry | CommentBankSuggestion;
  isLocked: boolean;
  isApplied: boolean;
  isDeleting: boolean;
  onApply: () => void;
  onDelete: () => void;
}

function BankEntryRow({
  entry,
  isLocked,
  isApplied,
  isDeleting,
  onApply,
  onDelete,
}: BankEntryRowProps) {
  return (
    <li className="rounded-md bg-white px-3 py-2 text-xs shadow-sm ring-1 ring-gray-200">
      <p className="mb-2 text-gray-800 line-clamp-3">{entry.text}</p>
      {"score" in entry && (
        <p className="mb-1 text-xs text-gray-400">
          Match: {Math.round((entry as CommentBankSuggestion).score * 100)}%
        </p>
      )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={isLocked}
          onClick={onApply}
          aria-label="Apply saved comment"
          className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isApplied ? "Applied!" : "Apply"}
        </button>
        <button
          type="button"
          disabled={isDeleting}
          onClick={onDelete}
          aria-label="Delete saved comment"
          className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isDeleting ? "Deleting…" : "Delete"}
        </button>
      </div>
    </li>
  );
}
