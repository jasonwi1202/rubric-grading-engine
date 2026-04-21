"use client";

/**
 * BatchGradingPanel — trigger batch grading and display real-time progress.
 *
 * Features:
 * - "Grade now" button that triggers POST /assignments/{id}/grade
 * - Progress bar that polls GET /assignments/{id}/grading-status every 3 s
 * - Polling stops automatically when all essays are complete or failed
 * - Per-essay status list (queued / grading / complete / failed)
 * - Failed essays show error type code — never raw exceptions or essay content
 * - Per-essay retry button shown only for failed essays
 * - In-app notification (aria-live region) on batch completion
 *
 * Security:
 * - No essay content or student PII is displayed in error messages.
 * - Error codes from the backend are mapped to short human-readable labels;
 *   raw `error` strings from the API are never rendered verbatim.
 * - Entity IDs only in any logging paths.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  triggerGrading,
  getGradingStatus,
  retryEssayGrading,
} from "@/lib/api/grading";
import type {
  GradingStatusResponse,
  EssayGradingEntry,
  EssayGradingStatus,
} from "@/lib/api/grading";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Polling interval while grading is in-progress (milliseconds). */
export const POLL_INTERVAL_MS = 3000;

/** Terminal batch statuses — polling stops when reached. */
const TERMINAL_STATUSES = new Set(["complete", "failed", "partial"]);

/**
 * Human-readable labels for per-essay grading status badges.
 * Backend uses "complete" for successfully graded essays.
 */
const ESSAY_STATUS_LABELS: Record<EssayGradingStatus, string> = {
  queued: "Queued",
  grading: "Grading…",
  complete: "Complete",
  failed: "Failed",
};

const ESSAY_STATUS_COLORS: Record<EssayGradingStatus, string> = {
  queued: "bg-gray-100 text-gray-600",
  grading: "bg-blue-100 text-blue-700",
  complete: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

/**
 * Map backend error type codes to short teacher-facing descriptions.
 * Any unknown code falls back to a generic label.
 * Raw exception messages are never shown.
 */
const ERROR_TYPE_LABELS: Record<string, string> = {
  LLM_TIMEOUT: "AI request timed out",
  PARSE_ERROR: "AI response could not be parsed",
  VALIDATION_ERROR: "Response failed validation",
  RATE_LIMIT: "AI rate limit reached",
  CONTENT_FILTER: "Content flagged by AI filter",
};

function errorLabel(code: string | null | undefined): string {
  if (!code) return "Unknown error";
  return ERROR_TYPE_LABELS[code] ?? "Grading error";
}

/**
 * Map API error codes from the retry endpoint to teacher-facing messages.
 * Never shows raw exception text or internal server details.
 */
function retryErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "NOT_FOUND":
        return "Essay not found. Please refresh the page.";
      case "FORBIDDEN":
        return "You do not have permission to retry this essay.";
      case "CONFLICT":
        return "This essay is already being graded.";
      default:
        return "Retry failed. Please try again.";
    }
  }
  return "Retry failed. Please try again.";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function EssayStatusBadge({ status }: { status: EssayGradingStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${ESSAY_STATUS_COLORS[status]}`}
    >
      {ESSAY_STATUS_LABELS[status]}
    </span>
  );
}

function ProgressBar({
  complete,
  failed,
  total,
}: {
  complete: number;
  failed: number;
  total: number;
}) {
  const pct = total > 0 ? Math.round(((complete + failed) / total) * 100) : 0;
  return (
    <div aria-label={`Grading progress: ${pct}%`}>
      <div className="mb-1 flex items-center justify-between text-xs text-gray-600">
        <span>
          {complete} of {total} complete
          {failed > 0 && (
            <span className="ml-2 text-red-600">{failed} failed</span>
          )}
        </span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-full rounded-full bg-blue-500 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function EssayRow({
  essay,
  onRetry,
  isRetrying,
}: {
  essay: EssayGradingEntry;
  onRetry: (essayId: string) => void;
  isRetrying: boolean;
}) {
  return (
    <tr className="hover:bg-gray-50">
      <td className="px-4 py-3">
        <span className="font-mono text-xs text-gray-400">
          {essay.id.slice(0, 8)}…
        </span>
      </td>
      <td className="px-4 py-3">
        <EssayStatusBadge status={essay.status} />
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">
        {essay.status === "failed" ? errorLabel(essay.error) : null}
      </td>
      <td className="px-4 py-3 text-right">
        {essay.status === "failed" && (
          <button
            type="button"
            onClick={() => onRetry(essay.id)}
            disabled={isRetrying}
            aria-label={`Retry grading for essay ${essay.id.slice(0, 8)}`}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:opacity-50"
          >
            {isRetrying ? "Retrying…" : "Retry"}
          </button>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface BatchGradingPanelProps {
  assignmentId: string;
  /**
   * Whether the assignment is in a gradeable state.
   * The "Grade now" button is only shown when this is true.
   */
  canGrade: boolean;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function BatchGradingPanel({
  assignmentId,
  canGrade,
}: BatchGradingPanelProps) {
  const queryClient = useQueryClient();

  // ----- Grading status query -----
  // Always fetches once on mount to check current grading state.
  // refetchInterval drives continuous polling only while grading is active —
  // returns `false` when status is idle or terminal, preventing unnecessary requests.
  const {
    data: gradingStatus,
    isLoading: statusLoading,
    isError: statusError,
  } = useQuery<GradingStatusResponse>({
    queryKey: ["grading-status", assignmentId],
    queryFn: () => getGradingStatus(assignmentId),
    enabled: !!assignmentId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      // Stop polling once we reach a terminal state
      if (TERMINAL_STATUSES.has(data.status)) return false;
      // No polling when idle (grading not started)
      if (data.status === "idle") return false;
      return POLL_INTERVAL_MS;
    },
    // Don't pause polling on window focus events — we want continuous updates
    refetchOnWindowFocus: false,
    staleTime: 0,
    retry: false,
  });

  // When the batch reaches a terminal state
  const isTerminal =
    gradingStatus != null && TERMINAL_STATUSES.has(gradingStatus.status);
  // isIdle is true only when a status has been fetched and is explicitly idle
  const isIdle = gradingStatus?.status === "idle";

  // ----- Trigger grading -----
  const triggerMutation = useMutation({
    mutationFn: () => triggerGrading(assignmentId),
    onSuccess: () => {
      // Invalidate assignment detail so status badge updates
      void queryClient.invalidateQueries({
        queryKey: ["assignment", assignmentId],
      });
      // Refetch grading status immediately so the progress bar appears
      void queryClient.invalidateQueries({
        queryKey: ["grading-status", assignmentId],
      });
    },
  });

  // ----- Per-essay retry -----
  const [retryErrors, setRetryErrors] = useState<Record<string, string>>({});

  const retryMutation = useMutation({
    mutationFn: (essayId: string) => retryEssayGrading(essayId),
    onSuccess: (_, essayId) => {
      setRetryErrors((prev) => {
        const next = { ...prev };
        delete next[essayId];
        return next;
      });
      // Refetch grading status to show updated essay progress
      void queryClient.invalidateQueries({
        queryKey: ["grading-status", assignmentId],
      });
    },
    onError: (err: unknown, essayId) => {
      setRetryErrors((prev) => ({
        ...prev,
        [essayId]: retryErrorMessage(err),
      }));
    },
  });

  const handleRetry = (essayId: string) => {
    setRetryErrors((prev) => {
      const next = { ...prev };
      delete next[essayId];
      return next;
    });
    retryMutation.mutate(essayId);
  };

  // ----- Derived state -----
  const isGrading =
    gradingStatus != null &&
    (gradingStatus.status === "processing" ||
      gradingStatus.essays.some(
        (e) => e.status === "queued" || e.status === "grading",
      ));

  const completionMessage = (() => {
    if (!gradingStatus) return null;
    if (gradingStatus.status === "complete") {
      return `Grading complete. ${gradingStatus.complete} essay${gradingStatus.complete !== 1 ? "s" : ""} graded successfully.`;
    }
    if (gradingStatus.status === "partial") {
      return `Grading finished. ${gradingStatus.complete} graded, ${gradingStatus.failed} failed.`;
    }
    if (gradingStatus.status === "failed") {
      return `Grading failed for all essays. Use the retry buttons below.`;
    }
    return null;
  })();

  return (
    <section aria-labelledby="batch-grading-heading" className="space-y-4">
      <div className="flex items-center justify-between">
        <h2
          id="batch-grading-heading"
          className="text-base font-semibold text-gray-900"
        >
          Batch grading
        </h2>

        {/* Grade now button — only shown when assignment is gradeable */}
        {canGrade && (isIdle || isTerminal) && (
          <button
            type="button"
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending || isGrading}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          >
            {triggerMutation.isPending ? "Starting…" : "Grade now"}
          </button>
        )}
      </div>

      {/* Trigger error */}
      {triggerMutation.isError && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Failed to start grading. Please try again.
        </p>
      )}

      {/* Status fetch error */}
      {statusError && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Unable to load grading progress. Please refresh.
        </p>
      )}

      {/* In-app completion notification */}
      <div aria-live="polite" aria-atomic="true">
        {completionMessage && (
          <p
            className={`rounded-md px-4 py-3 text-sm font-medium ${
              gradingStatus?.status === "complete"
                ? "bg-green-50 text-green-700"
                : gradingStatus?.status === "partial"
                  ? "bg-amber-50 text-amber-700"
                  : "bg-red-50 text-red-700"
            }`}
          >
            {completionMessage}
          </p>
        )}
      </div>

      {/* Progress bar */}
      {gradingStatus && !isIdle && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
          <ProgressBar
            complete={gradingStatus.complete}
            failed={gradingStatus.failed}
            total={gradingStatus.total}
          />

          {/* Per-essay status table */}
          {gradingStatus.essays.length > 0 && (
            <div className="mt-4 overflow-hidden rounded-lg border border-gray-200">
              <table
                className="min-w-full divide-y divide-gray-200 text-sm"
                aria-label="Per-essay grading status"
              >
                <thead className="bg-gray-50">
                  <tr>
                    <th
                      scope="col"
                      className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                    >
                      Essay
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                    >
                      Status
                    </th>
                    <th
                      scope="col"
                      className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                    >
                      Error
                    </th>
                    <th scope="col" className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {gradingStatus.essays.map((essay) => (
                    <EssayRow
                      key={essay.id}
                      essay={essay}
                      onRetry={handleRetry}
                      isRetrying={
                        retryMutation.isPending &&
                        retryMutation.variables === essay.id
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Per-essay retry errors */}
          {Object.keys(retryErrors).length > 0 && (
            <ul
              role="alert"
              aria-live="polite"
              className="mt-2 space-y-1"
            >
              {Object.entries(retryErrors).map(([id, msg]) => (
                <li key={id} className="text-sm text-red-700">
                  {msg}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Idle state — no grading has started yet */}
      {isIdle && !triggerMutation.isPending && !triggerMutation.isError && (
        <p className="text-sm text-gray-500">
          {canGrade
            ? 'Click "Grade now" to start AI grading for all queued essays.'
            : "Grading is not available for this assignment yet."}
        </p>
      )}
    </section>
  );
}
