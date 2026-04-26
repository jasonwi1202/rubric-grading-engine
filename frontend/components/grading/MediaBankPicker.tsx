"use client";

/**
 * MediaBankPicker — media comment bank picker for EssayReviewPanel.
 *
 * Features:
 * - Lists all banked (reusable) media comments for the authenticated teacher.
 * - Each entry shows duration, MIME type, and an "Apply" button.
 * - Applying a banked comment copies the S3 recording to the target grade
 *   via POST /grades/{gradeId}/media-comments with source_id, then
 *   invalidates the grade's media comment query so the list refreshes.
 * - Disabled when the grade is locked.
 *
 * Security:
 * - No student PII in any log or error path.
 * - Entity IDs only in error payloads.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  applyBankedComment,
  listBankedComments,
} from "@/lib/api/media-comments";
import type { MediaCommentResponse } from "@/lib/api/media-comments";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function applyErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to apply this comment.";
      case "NOT_FOUND":
        return "Media comment not found. It may have been deleted.";
      default:
        return "Failed to apply media comment. Please try again.";
    }
  }
  return "Failed to apply media comment. Please try again.";
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface MediaBankPickerProps {
  /** UUID of the grade to apply comments to. */
  gradeId: string;
  /** When true, the Apply button is disabled. */
  isLocked: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MediaBankPicker({ gradeId, isLocked }: MediaBankPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [appliedId, setAppliedId] = useState<string | null>(null);
  const appliedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queryClient = useQueryClient();

  // Clear any pending "Applied!" reset timer on unmount to avoid setting state
  // on an unmounted component.
  useEffect(() => {
    return () => {
      if (appliedTimerRef.current !== null) {
        clearTimeout(appliedTimerRef.current);
      }
    };
  }, []);

  const {
    data: bankComments,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["media-bank"],
    queryFn: listBankedComments,
    enabled: isOpen,
    staleTime: 30_000,
  });

  const applyMutation = useMutation({
    mutationFn: (sourceId: string) => applyBankedComment(gradeId, sourceId),
    onSuccess: (_data, sourceId) => {
      setApplyError(null);
      setAppliedId(sourceId);
      // Invalidate the grade's media comment list so it refreshes.
      void queryClient.invalidateQueries({
        queryKey: ["media-comments", gradeId],
      });
      // Reset applied indicator after 2 seconds; clear any prior timer first.
      if (appliedTimerRef.current !== null) {
        clearTimeout(appliedTimerRef.current);
      }
      appliedTimerRef.current = setTimeout(() => {
        setAppliedId(null);
        appliedTimerRef.current = null;
      }, 2000);
    },
    onError: (err: unknown) => {
      setApplyError(applyErrorMessage(err));
    },
  });

  const isEmpty = !isLoading && !isError && (!bankComments || bankComments.length === 0);

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        aria-expanded={isOpen}
        aria-controls="media-bank-picker-list"
        disabled={isLocked}
        className="flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
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
            d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
          />
        </svg>
        {isOpen ? "Hide media bank" : "Apply from media bank"}
      </button>

      {isOpen && (
        <div
          id="media-bank-picker-list"
          className="mt-2 rounded-md border border-gray-200 bg-gray-50 p-3"
          role="region"
          aria-label="Media comment bank"
        >
          {isLoading && (
            <p className="text-xs text-gray-500" aria-live="polite">
              Loading saved comments…
            </p>
          )}

          {isError && (
            <p className="text-xs text-red-600" role="alert">
              Failed to load the media comment bank. Please try again.
            </p>
          )}

          {isEmpty && (
            <p className="text-xs text-gray-500">
              No saved media comments yet. Record a comment and click
              &ldquo;Save to bank&rdquo; to add it here.
            </p>
          )}

          {applyError && (
            <p className="mb-2 text-xs text-red-600" role="alert">
              {applyError}
            </p>
          )}

          {bankComments && bankComments.length > 0 && (
            <ul className="space-y-2" aria-label="Saved media comments">
              {bankComments.map((comment: MediaCommentResponse) => (
                <BankCommentRow
                  key={comment.id}
                  comment={comment}
                  isLocked={isLocked}
                  isApplying={applyMutation.isPending}
                  isApplied={appliedId === comment.id}
                  onApply={() => applyMutation.mutate(comment.id)}
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
// BankCommentRow — individual entry in the bank picker
// ---------------------------------------------------------------------------

interface BankCommentRowProps {
  comment: MediaCommentResponse;
  isLocked: boolean;
  isApplying: boolean;
  isApplied: boolean;
  onApply: () => void;
}

function BankCommentRow({
  comment,
  isLocked,
  isApplying,
  isApplied,
  onApply,
}: BankCommentRowProps) {
  const isAudio = comment.mime_type.startsWith("audio/");
  const typeLabel = isAudio ? "Audio" : "Video";

  return (
    <li className="flex items-center justify-between gap-2 rounded-md bg-white px-3 py-2 text-xs shadow-sm ring-1 ring-gray-200">
      <span className="flex items-center gap-1.5 text-gray-700">
        <svg
          aria-hidden="true"
          className="h-3.5 w-3.5 shrink-0 text-blue-500"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d={
              isAudio
                ? "M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
                : "M15 10l4.553-2.276A1 1 0 0121 8.723v6.554a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
            }
          />
        </svg>
        <span>
          {typeLabel} · {formatDuration(comment.duration_seconds)}
        </span>
      </span>

      <button
        type="button"
        disabled={isLocked || isApplying}
        onClick={onApply}
        aria-label={`Apply saved ${typeLabel.toLowerCase()} comment to this grade`}
        className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isApplying ? "Applying…" : isApplied ? "Applied!" : "Apply"}
      </button>
    </li>
  );
}
