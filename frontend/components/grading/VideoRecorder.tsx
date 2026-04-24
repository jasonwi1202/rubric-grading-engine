"use client";

/**
 * VideoRecorder — in-browser webcam video comment recording for EssayReviewPanel.
 *
 * Features:
 * - Record / Stop button powered by the MediaRecorder API using
 *   getUserMedia({video: true, audio: true}).
 * - Optional screen share toggle: calls getDisplayMedia and combines the
 *   screen video track with microphone audio from getUserMedia.
 * - Records as video/webm; same 3-minute (180 s) max limit as AudioRecorder.
 * - Live camera preview while recording.
 * - After stopping, the recording is immediately playable for review.
 * - Save uploads the blob to the backend (which stores it in S3) and adds
 *   the comment to the grade's list.
 * - Existing comments listed with Play and Delete buttons.
 * - Graceful degradation: if getUserMedia is denied for video, an audio-only
 *   fallback is offered; if that too is denied, an error is shown.
 * - Locked grades: recording and delete controls are disabled.
 *
 * Security:
 * - No student PII in any log or error path.
 * - Video blobs are never written to localStorage or sessionStorage.
 * - Entity IDs only in error payloads.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  uploadMediaComment,
  listGradeMediaComments,
  deleteMediaComment,
  getMediaCommentUrl,
} from "@/lib/api/media-comments";
import type { MediaCommentResponse } from "@/lib/api/media-comments";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_DURATION_SECONDS = 180; // 3 minutes
const VIDEO_MIME_TYPE = "video/webm";

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

/** Safely call element.play() and swallow autoplay-blocked rejections. */
function safePlay(el: HTMLVideoElement | null): void {
  if (!el) return;
  const result = el.play();
  if (result && typeof result.catch === "function") {
    result.catch(() => {
      // Autoplay may be blocked — user can retry.
    });
  }
}

/**
 * Returns true when the DOMException name indicates a permission denial,
 * as opposed to hardware errors (NotFoundError, NotReadableError, etc.).
 */
function isPermissionDenied(err: unknown): boolean {
  if (err instanceof Error) {
    return err.name === "NotAllowedError" || err.name === "PermissionDeniedError";
  }
  return false;
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

export interface VideoRecorderProps {
  /** UUID of the grade these comments are attached to. */
  gradeId: string;
  /** When true, recording and delete controls are disabled. */
  isLocked: boolean;
}

// ---------------------------------------------------------------------------
// VideoCommentRow — a single saved video media comment entry
// ---------------------------------------------------------------------------

function VideoCommentRow({
  comment,
  isLocked,
  onDeleted,
}: {
  comment: MediaCommentResponse;
  isLocked: boolean;
  onDeleted: () => void;
}) {
  const [playUrl, setPlayUrl] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [isLoadingUrl, setIsLoadingUrl] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const deleteMutation = useMutation({
    mutationFn: () => deleteMediaComment(comment.id),
    onSuccess: () => {
      onDeleted();
    },
    onError: (err) => {
      setDeleteError(deleteErrorMessage(err));
    },
  });

  const handlePlay = useCallback(async () => {
    setUrlError(null);
    if (playUrl) {
      safePlay(videoRef.current);
      return;
    }
    setIsLoadingUrl(true);
    try {
      const { url } = await getMediaCommentUrl(comment.id);
      setPlayUrl(url);
      // Video element will start once src is set.
    } catch (err) {
      console.error("Failed to load media comment URL:", {
        error_type: err instanceof Error ? err.constructor.name : typeof err,
      });
      setUrlError("Could not load playback URL. Please try again.");
    } finally {
      setIsLoadingUrl(false);
    }
  }, [playUrl, comment.id]);

  // Auto-play when URL first becomes available.
  useEffect(() => {
    if (playUrl) {
      safePlay(videoRef.current);
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
            aria-label={`Play video comment recorded on ${createdDate}`}
            className="rounded px-2 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoadingUrl ? "Loading…" : "Play"}
          </button>
          {!isLocked && (
            <button
              type="button"
              onClick={() => {
                setDeleteError(null);
                deleteMutation.mutate();
              }}
              disabled={deleteMutation.isPending}
              aria-label={`Delete video comment recorded on ${createdDate}`}
              className="rounded px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {deleteMutation.isPending ? "Deleting…" : "Delete"}
            </button>
          )}
        </div>
      </div>

      {/* Hidden video element — src set when playUrl is available */}
      {playUrl && (
        <video
          ref={videoRef}
          src={playUrl}
          controls
          aria-label="Video comment playback"
          className="mt-1 w-full rounded"
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
    </li>
  );
}

// ---------------------------------------------------------------------------
// VideoRecorder — main component
// ---------------------------------------------------------------------------

export function VideoRecorder({ gradeId, isLocked }: VideoRecorderProps) {
  const queryClient = useQueryClient();

  // Existing comments query — shared key with AudioRecorder; filter to video only.
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
  const [screenShareEnabled, setScreenShareEnabled] = useState(false);
  const [isAudioFallback, setIsAudioFallback] = useState(false);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const liveVideoRef = useRef<HTMLVideoElement | null>(null);

  // Clear timer on unmount.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  // Create and revoke a preview object URL whenever the recorded blob changes.
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
    setIsAudioFallback(false);

    let stream: MediaStream;
    let audioOnlyFallback = false;

    if (screenShareEnabled) {
      // Screen share: capture display video, then add microphone audio.
      let screenStream: MediaStream;
      try {
        screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      } catch {
        setPermissionError(
          "Screen share access was denied. Please allow screen sharing and try again.",
        );
        return;
      }
      try {
        const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream = new MediaStream([
          ...screenStream.getVideoTracks(),
          ...audioStream.getAudioTracks(),
        ]);
      } catch {
        // Proceed with screen video only (no microphone audio).
        stream = screenStream;
      }
    } else {
      // Webcam + microphone recording.
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      } catch (videoErr) {
        // Only offer audio-only fallback for permission denials, not hardware errors.
        const isDenied = isPermissionDenied(videoErr);
        if (!isDenied) {
          setPermissionError(
            "Camera is unavailable or in use. Please check your device and try again.",
          );
          return;
        }
        // Camera access denied — offer audio-only fallback.
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          audioOnlyFallback = true;
          setIsAudioFallback(true);
          setPermissionError(
            "Camera access was denied. Recording audio only. Enable camera access in your browser settings for video.",
          );
        } catch {
          setPermissionError(
            "Microphone and camera access were denied. Please enable them in your browser settings and try again.",
          );
          return;
        }
      }
    }

    // Show live camera preview while recording (not for screen share or audio fallback).
    if (liveVideoRef.current && !audioOnlyFallback && !screenShareEnabled) {
      liveVideoRef.current.srcObject = stream;
    }

    chunksRef.current = [];
    const mimeType = audioOnlyFallback ? "audio/webm" : VIDEO_MIME_TYPE;
    let recorder: MediaRecorder;
    try {
      recorder =
        typeof MediaRecorder !== "undefined" &&
        typeof MediaRecorder.isTypeSupported === "function" &&
        MediaRecorder.isTypeSupported(mimeType)
          ? new MediaRecorder(stream, { mimeType })
          : new MediaRecorder(stream);
    } catch (err) {
      // MediaRecorder not supported in this browser.
      console.error("MediaRecorder initialization failed:", {
        error_type: err instanceof Error ? err.constructor.name : typeof err,
      });
      stream.getTracks().forEach((t) => t.stop());
      setPermissionError(
        "Video recording is not supported in this browser. Please try a different browser.",
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
      const blobMimeType = recorder.mimeType || mimeType;
      const blob = new Blob(chunksRef.current, { type: blobMimeType });
      const elapsed = Math.ceil((Date.now() - startTimeRef.current) / 1000);
      setRecordedBlob(blob);
      setRecordedDuration(Math.min(Math.max(elapsed, 1), MAX_DURATION_SECONDS));
      // Stop all tracks to release camera / screen capture.
      stream.getTracks().forEach((t) => t.stop());
      // Clear live preview.
      if (liveVideoRef.current) {
        liveVideoRef.current.srcObject = null;
      }
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
  }, [isRecording, stopRecording, screenShareEnabled]);

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
      setIsAudioFallback(false);
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
    setIsAudioFallback(false);
  };

  const handleCommentDeleted = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: ["media-comments", gradeId],
    });
  }, [gradeId, queryClient]);

  // Filter to video-type comments only (audio comments are shown in AudioRecorder).
  const comments = (commentsQuery.data ?? []).filter((c) =>
    c.mime_type.startsWith("video/"),
  );

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-gray-700">Video comment</h3>

      {/* Screen share toggle — only available when not recording */}
      {!isLocked && !isRecording && !recordedBlob && (
        <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-600">
          <input
            type="checkbox"
            checked={screenShareEnabled}
            onChange={(e) => setScreenShareEnabled(e.target.checked)}
            aria-label="Enable screen share recording"
            className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Share screen instead of webcam
        </label>
      )}

      {/* Record / Stop button */}
      {!isLocked && !recordedBlob && (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              void handleStartStop();
            }}
            aria-label={isRecording ? "Stop recording" : "Start recording video comment"}
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
              className="font-mono text-sm text-red-700"
              aria-live="polite"
              aria-label={`${formatCountdown(countdown)} remaining`}
            >
              {formatCountdown(countdown)}
            </span>
          )}
        </div>
      )}

      {/* Live camera preview while recording */}
      {isRecording && !screenShareEnabled && !isAudioFallback && (
        <video
          ref={liveVideoRef}
          autoPlay
          muted
          playsInline
          aria-label="Live camera preview"
          className="w-full max-w-xs rounded border border-gray-300"
        />
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
            {isAudioFallback ? "Audio" : "Video"} recording ready (
            {formatDuration(recordedDuration)}) — review before saving:
          </p>
          {isAudioFallback ? (
            <audio
              src={previewUrl ?? undefined}
              controls
              aria-label="Preview of new audio recording"
              className="w-full"
            />
          ) : (
            <video
              src={previewUrl ?? undefined}
              controls
              aria-label="Preview of new video recording"
              className="w-full rounded"
            />
          )}
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
              aria-label={isAudioFallback ? "Save audio comment" : "Save video comment"}
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
        <ul className="space-y-2" aria-label="Saved video comments">
          {comments.map((c) => (
            <VideoCommentRow
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
          Failed to load video comments. Please refresh the page.
        </p>
      )}
    </div>
  );
}
