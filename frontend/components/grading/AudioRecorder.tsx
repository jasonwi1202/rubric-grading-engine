"use client";

/**
 * AudioRecorder — in-browser audio comment recording for EssayReviewPanel.
 *
 * Features:
 * - Record / Stop button powered by the MediaRecorder API.
 * - Max 3-minute (180 s) recording limit enforced client-side with a live
 *   countdown timer.
 * - After stopping, the recording is immediately playable for review.
 * - Save uploads the blob to the backend (which stores it in S3) and adds
 *   the comment to the grade's list.
 * - Existing comments are listed with a Play button (presigned URL fetched
 *   on demand) and a Delete button.
 * - Degrades gracefully when microphone permission is denied.
 * - Locked grades: recording and delete controls are disabled.
 *
 * Security:
 * - No student PII in any log or error path.
 * - Audio blobs are never written to localStorage or sessionStorage.
 * - Entity IDs only in error payloads.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  uploadMediaComment,
  listGradeMediaComments,
  deleteMediaComment,
  getMediaCommentUrl,
  saveToBank,
} from "@/lib/api/media-comments";
import type { MediaCommentResponse } from "@/lib/api/media-comments";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_DURATION_SECONDS = 180; // 3 minutes

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCountdown(remaining: number): string {
  const m = Math.floor(remaining / 60);
  const s = remaining % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function recordErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to add a media comment.";
      case "NOT_FOUND":
        return "Grade not found. Please refresh the page.";
      case "VALIDATION_ERROR":
        return "Recording could not be saved — file too large or format not supported.";
      default:
        return "Failed to save recording. Please try again.";
    }
  }
  return "Failed to save recording. Please try again.";
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
// Types
// ---------------------------------------------------------------------------

export interface AudioRecorderProps {
  /** UUID of the grade these comments are attached to. */
  gradeId: string;
  /** When true, recording and delete controls are disabled. */
  isLocked: boolean;
}

// ---------------------------------------------------------------------------
// CommentRow — a single saved media comment entry
// ---------------------------------------------------------------------------

function CommentRow({
  comment,
  isLocked,
  onDeleted,
}: {
  comment: MediaCommentResponse;
  isLocked: boolean;
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const [playUrl, setPlayUrl] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [isLoadingUrl, setIsLoadingUrl] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [bankError, setBankError] = useState<string | null>(null);
  const [isBanked, setIsBanked] = useState(comment.is_banked);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Keep local banked state in sync with query data so that a background
  // refetch (e.g., from another session) is reflected immediately.
  useEffect(() => {
    setIsBanked(comment.is_banked);
  }, [comment.is_banked]);

  const deleteMutation = useMutation({
    mutationFn: () => deleteMediaComment(comment.id),
    onSuccess: () => {
      onDeleted();
    },
    onError: (err) => {
      setDeleteError(deleteErrorMessage(err));
    },
  });

  const saveToBankMutation = useMutation({
    mutationFn: () => saveToBank(comment.id),
    onSuccess: () => {
      setBankError(null);
      setIsBanked(true);
      // Invalidate the bank list so it refreshes when the picker is opened.
      void queryClient.invalidateQueries({ queryKey: ["media-bank"] });
    },
    onError: () => {
      setBankError("Failed to save to bank. Please try again.");
    },
  });

  const handlePlay = useCallback(async () => {
    setUrlError(null);
    if (playUrl) {
      const result = audioRef.current?.play();
      if (result && typeof result.catch === "function") {
        result.catch(() => {
          // Autoplay may be blocked — user can retry.
        });
      }
      return;
    }
    setIsLoadingUrl(true);
    try {
      const { url } = await getMediaCommentUrl(comment.id);
      setPlayUrl(url);
      // Audio element will start once src is set.
    } catch {
      setUrlError("Could not load playback URL. Please try again.");
    } finally {
      setIsLoadingUrl(false);
    }
  }, [playUrl, comment.id]);

  // Auto-play when URL first becomes available.
  useEffect(() => {
    if (playUrl && audioRef.current) {
      const result = audioRef.current.play();
      if (result && typeof result.catch === "function") {
        result.catch(() => {
          // Blocked — user pressed play anyway.
        });
      }
    }
  }, [playUrl]);

  const createdDate = new Date(comment.created_at).toLocaleString();

  return (
    <li className="flex flex-col gap-1 rounded-md border border-gray-200 bg-gray-50 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-gray-500">
          {createdDate} · {formatDuration(comment.duration_seconds)}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handlePlay}
            disabled={isLoadingUrl}
            aria-label={`Play audio comment recorded on ${createdDate}`}
            className="rounded px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoadingUrl ? "Loading…" : "Play"}
          </button>
          {!isLocked && (
            <>
              <button
                type="button"
                onClick={() => {
                  setBankError(null);
                  saveToBankMutation.mutate();
                }}
                disabled={saveToBankMutation.isPending || isBanked}
                aria-label={
                  isBanked
                    ? "Audio comment is already saved to bank"
                    : "Save audio comment to reusable bank"
                }
                className="rounded px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isBanked ? "In bank" : saveToBankMutation.isPending ? "Saving…" : "Save to bank"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setDeleteError(null);
                  deleteMutation.mutate();
                }}
                disabled={deleteMutation.isPending}
                aria-label={`Delete audio comment recorded on ${createdDate}`}
                className="rounded px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting…" : "Delete"}
              </button>
            </>
          )}
        </div>
      </div>

      {/* Hidden audio element — src set when playUrl is available */}
      {playUrl && (
        <audio
          ref={audioRef}
          src={playUrl}
          controls
          aria-label="Audio comment playback"
          className="mt-1 w-full"
        />
      )}

      {urlError && (
        <p role="alert" className="mt-1 text-xs text-red-700">
          {urlError}
        </p>
      )}
      {deleteError && (
        <p role="alert" className="mt-1 text-xs text-red-700">
          {deleteError}
        </p>
      )}
      {bankError && (
        <p role="alert" className="mt-1 text-xs text-red-700">
          {bankError}
        </p>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// AudioRecorder — main component
// ---------------------------------------------------------------------------

export function AudioRecorder({ gradeId, isLocked }: AudioRecorderProps) {
  const queryClient = useQueryClient();

  // Existing comments query.
  const commentsQuery = useQuery({
    queryKey: ["media-comments", gradeId],
    queryFn: () => listGradeMediaComments(gradeId),
    staleTime: 60_000,
  });

  // Recording state.
  const [isRecording, setIsRecording] = useState(false);
  const [countdown, setCountdown] = useState(MAX_DURATION_SECONDS);
  const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null);
  const [recordedDuration, setRecordedDuration] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [permissionError, setPermissionError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  // Clear timer on unmount.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  // Create and revoke a preview object URL whenever the recorded blob changes.
  // Revoking on cleanup prevents memory leaks from repeated recordings.
  useEffect(() => {
    if (!recordedBlob) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(recordedBlob);
    setPreviewUrl(url);
    return () => {
      URL.revokeObjectURL(url);
    };
  }, [recordedBlob]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setIsRecording(false);
  }, []);

  const handleStartStop = useCallback(async () => {
    if (isRecording) {
      stopRecording();
      return;
    }

    setPermissionError(null);
    setSaveError(null);
    setRecordedBlob(null);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setPermissionError(
        "Microphone access was denied. Please enable it in your browser settings and try again.",
      );
      return;
    }

    chunksRef.current = [];
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream);
    } catch (err) {
      // MediaRecorder is not supported in this browser (e.g. some Safari versions).
      // Log for debugging without exposing PII — the error is a DOMException.
      console.error("MediaRecorder initialization failed:", err);
      stream.getTracks().forEach((t) => t.stop());
      setPermissionError(
        "Audio recording is not supported in this browser. Please try a different browser.",
      );
      return;
    }
    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        chunksRef.current.push(e.data);
      }
    };

    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, {
        type: recorder.mimeType || "audio/webm",
      });
      const elapsed = Math.ceil((Date.now() - startTimeRef.current) / 1000);
      setRecordedBlob(blob);
      setRecordedDuration(Math.min(Math.max(elapsed, 1), MAX_DURATION_SECONDS));
      // Stop all tracks to release the microphone.
      stream.getTracks().forEach((t) => t.stop());
    };

    startTimeRef.current = Date.now();
    setCountdown(MAX_DURATION_SECONDS);
    setIsRecording(true);
    recorder.start(1000); // collect data every second

    // Countdown timer — auto-stop at limit.
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          stopRecording();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, [isRecording, stopRecording]);

  // Upload mutation.
  const saveMutation = useMutation({
    mutationFn: () => {
      if (!recordedBlob) throw new Error("No recording to save.");
      return uploadMediaComment(gradeId, recordedBlob, recordedDuration);
    },
    onSuccess: () => {
      setRecordedBlob(null);
      setRecordedDuration(0);
      setCountdown(MAX_DURATION_SECONDS);
      void queryClient.invalidateQueries({
        queryKey: ["media-comments", gradeId],
      });
    },
    onError: (err) => {
      setSaveError(recordErrorMessage(err));
    },
  });

  const handleDiscard = () => {
    setRecordedBlob(null);
    setRecordedDuration(0);
    setCountdown(MAX_DURATION_SECONDS);
    setSaveError(null);
  };

  const handleCommentDeleted = useCallback(
    () => {
      void queryClient.invalidateQueries({
        queryKey: ["media-comments", gradeId],
      });
    },
    [gradeId, queryClient],
  );

  const comments = (commentsQuery.data ?? []).filter((c) =>
    c.mime_type.startsWith("audio/"),
  );

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-gray-700">Audio comment</h3>

      {/* Record / Stop button */}
      {!isLocked && !recordedBlob && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              void handleStartStop();
            }}
            aria-label={isRecording ? "Stop recording" : "Start recording audio comment"}
            aria-pressed={isRecording}
            className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-semibold shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 ${
              isRecording
                ? "bg-red-600 text-white hover:bg-red-700 focus:ring-red-500"
                : "bg-gray-800 text-white hover:bg-gray-700 focus:ring-gray-500"
            }`}
          >
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${
                isRecording ? "animate-pulse bg-white" : "bg-red-500"
              }`}
              aria-hidden="true"
            />
            {isRecording ? "Stop" : "Record"}
          </button>

          {isRecording && (
            <span
              className="text-sm font-mono text-red-700"
              aria-live="polite"
              aria-label={`${formatCountdown(countdown)} remaining`}
            >
              {formatCountdown(countdown)}
            </span>
          )}
        </div>
      )}

      {permissionError && (
        <p role="alert" className="text-xs text-red-700">
          {permissionError}
        </p>
      )}

      {/* Preview + save / discard controls after recording */}
      {recordedBlob && !isRecording && (
        <div className="space-y-2 rounded-md border border-blue-200 bg-blue-50 p-3">
          <p className="text-xs font-medium text-blue-800">
            Recording ready ({formatDuration(recordedDuration)}) — review before saving:
          </p>
          <audio
            src={previewUrl ?? undefined}
            controls
            aria-label="Preview of new audio recording"
            className="w-full"
          />
          {saveError && (
            <p role="alert" className="text-xs text-red-700">
              {saveError}
            </p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              aria-label="Save audio comment"
              className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={handleDiscard}
              disabled={saveMutation.isPending}
              aria-label="Discard this recording"
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Discard
            </button>
          </div>
        </div>
      )}

      {/* Existing comments list */}
      {comments.length > 0 && (
        <ul className="space-y-2" aria-label="Saved audio comments">
          {comments.map((c) => (
            <CommentRow
              key={c.id}
              comment={c}
              isLocked={isLocked}
              onDeleted={handleCommentDeleted}
            />
          ))}
        </ul>
      )}

      {commentsQuery.isError && (
        <p role="alert" className="text-xs text-red-700">
          Failed to load audio comments. Please refresh the page.
        </p>
      )}
    </div>
  );
}
