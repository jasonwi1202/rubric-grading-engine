"use client";

/**
 * RegradeQueue — regrade request queue and resolution panel.
 *
 * M4.9 implementation.
 *
 * Features:
 * - Queue tab: list of open regrade requests with student identifier,
 *   dispute text, and criterion name.
 * - Log request form: criterion selector (from rubric snapshot), dispute
 *   text field (max 500 chars), submit.
 * - Side-by-side review panel: original score + AI justification, dispute text.
 * - Approve controls: optional score override, confirm button.
 * - Deny controls: required resolution note, confirm button.
 * - Close regrade window action (teacher-explicit, with confirmation).
 *
 * Security:
 * - No student PII is included in log output — only entity IDs.
 * - Error messages are static strings; raw server text is never rendered.
 * - Essay content and student names are rendered only in the teacher-only
 *   dashboard and are never stored in localStorage or sessionStorage.
 */

import {
  useState,
  useId,
  useCallback,
} from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listRegradeRequests,
  createRegradeRequest,
  resolveRegradeRequest,
  closeRegradeWindow,
} from "@/lib/api/regrade-requests";
import type {
  RegradeRequest,
  RegradeRequestCreate,
  RegradeRequestResolveRequest,
} from "@/lib/api/regrade-requests";
import { getGrade } from "@/lib/api/grades";
import type { GradeResponse } from "@/lib/api/grades";
import { ApiError } from "@/lib/api/errors";
import type { EssayListItem } from "@/lib/api/essays";
import type { RubricSnapshotCriterion } from "@/components/grading/EssayReviewPanel";
import { useFocusTrap } from "@/lib/utils/focus-trap";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum characters allowed in a dispute text field (UI-enforced). */
export const DISPUTE_TEXT_MAX_CHARS = 500;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Abbreviate a UUID to its first 8 characters for display. */
function shortId(uuid: string): string {
  return uuid.slice(0, 8);
}

/** Format an ISO date string to a human-readable local date. */
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Error message helpers — static strings only, never raw server messages
// ---------------------------------------------------------------------------

function createErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to submit this request.";
      case "NOT_FOUND":
        return "Grade not found. Please refresh the page.";
      case "REGRADE_WINDOW_CLOSED":
        return "The regrade submission window has closed. No new requests can be submitted.";
      case "REGRADE_REQUEST_LIMIT_REACHED":
        return "The maximum number of regrade requests for this grade has been reached.";
      default:
        return "Failed to submit the regrade request. Please try again.";
    }
  }
  return "Failed to submit the regrade request. Please try again.";
}

function resolveErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to resolve this request.";
      case "NOT_FOUND":
        return "Regrade request not found. Please refresh.";
      case "VALIDATION_ERROR":
        return "A resolution note is required when denying a request.";
      default:
        return "Failed to resolve the request. Please try again.";
    }
  }
  return "Failed to resolve the request. Please try again.";
}

function closeWindowErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to close the regrade window.";
      case "NOT_FOUND":
        return "Assignment not found. Please refresh the page.";
      default:
        return "Failed to close the regrade window. Please try again.";
    }
  }
  // Non-ApiError means the backend endpoint isn't implemented yet (stub throws
  // a plain Error). Show a static "coming soon" message instead of a misleading
  // "failed — retry" message (retrying will always fail until the route ships).
  return "This feature is coming soon and is not yet available.";
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_LABELS: Record<RegradeRequest["status"], string> = {
  open: "Open",
  approved: "Approved",
  denied: "Denied",
};

const STATUS_COLORS: Record<RegradeRequest["status"], string> = {
  open: "bg-yellow-100 text-yellow-700",
  approved: "bg-green-100 text-green-700",
  denied: "bg-red-100 text-red-700",
};

// ---------------------------------------------------------------------------
// ReviewPanel — side-by-side dispute review and resolution
// ---------------------------------------------------------------------------

interface ReviewPanelProps {
  request: RegradeRequest;
  onResolve: (updated: RegradeRequest) => void;
  onClose: () => void;
}

function ReviewPanel({
  request,
  onResolve,
  onClose,
}: ReviewPanelProps) {
  const [resolution, setResolution] = useState<"approved" | "denied" | null>(
    null,
  );
  const [scoreOverride, setScoreOverride] = useState<string>("");
  const [resolutionNote, setResolutionNote] = useState("");
  const [resolveError, setResolveError] = useState<string | null>(null);

  const resolveId = useId();

  // Focus trap: captures focus on mount, traps Tab/Shift+Tab, Escape closes.
  const { dialogRef, handleKeyDown: trapKeyDown } = useFocusTrap({
    open: true,
    onClose,
  });

  const resolveMutation = useMutation({
    mutationFn: (body: RegradeRequestResolveRequest) =>
      resolveRegradeRequest(request.id, body),
    onSuccess: (updated) => {
      onResolve(updated);
    },
    onError: (err) => {
      setResolveError(resolveErrorMessage(err));
    },
  });

  const handleResolve = () => {
    if (!resolution) return;
    setResolveError(null);

    if (resolution === "denied" && !resolutionNote.trim()) {
      setResolveError("A resolution note is required when denying a request.");
      return;
    }

    const body: RegradeRequestResolveRequest = {
      resolution,
      resolution_note: resolutionNote.trim() || null,
    };

    if (resolution === "approved" && scoreOverride.trim() !== "") {
      const trimmedScoreOverride = scoreOverride.trim();
      const parsed = Number(trimmedScoreOverride);

      if (!Number.isInteger(parsed)) {
        setResolveError("Score override must be a whole number.");
        return;
      }

      body.new_criterion_score = parsed;
    }

    resolveMutation.mutate(body);
  };

  const isLocked = request.status !== "open";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${resolveId}-title`}
        className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onKeyDown={trapKeyDown}
        tabIndex={-1}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <h2
            id={`${resolveId}-title`}
            className="text-lg font-semibold text-gray-900"
          >
            Regrade Request Review
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Close review panel"
          >
            <svg
              aria-hidden="true"
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18 18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Body — two columns */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left: dispute details */}
          <div className="flex flex-1 flex-col gap-4 overflow-y-auto border-r border-gray-200 p-6">
            <section aria-labelledby={`${resolveId}-dispute-heading`}>
              <h3
                id={`${resolveId}-dispute-heading`}
                className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500"
              >
                Dispute details
              </h3>
              <dl className="space-y-2 text-sm">
                <div className="flex gap-2">
                  <dt className="shrink-0 font-medium text-gray-600">Request ID:</dt>
                  <dd className="font-mono text-gray-800">{shortId(request.id)}&hellip;</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="shrink-0 font-medium text-gray-600">Criterion:</dt>
                  <dd className="text-gray-800">
                    {request.criterion_score_id
                      ? "Specific criterion"
                      : "Overall grade"}
                  </dd>
                </div>
                <div className="flex gap-2">
                  <dt className="shrink-0 font-medium text-gray-600">Submitted:</dt>
                  <dd className="text-gray-800">{formatDate(request.created_at)}</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="shrink-0 font-medium text-gray-600">Status:</dt>
                  <dd>
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[request.status]}`}
                    >
                      {STATUS_LABELS[request.status]}
                    </span>
                  </dd>
                </div>
              </dl>
            </section>

            <section aria-labelledby={`${resolveId}-dispute-text-heading`}>
              <h3
                id={`${resolveId}-dispute-text-heading`}
                className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500"
              >
                Teacher-entered justification
              </h3>
              <blockquote className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-800 italic whitespace-pre-wrap">
                {request.dispute_text}
              </blockquote>
            </section>

            {request.resolution_note && (
              <section aria-labelledby={`${resolveId}-resolution-heading`}>
                <h3
                  id={`${resolveId}-resolution-heading`}
                  className="mb-2 text-sm font-semibold uppercase tracking-wide text-gray-500"
                >
                  Resolution note
                </h3>
                <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-800 whitespace-pre-wrap">
                  {request.resolution_note}
                </p>
              </section>
            )}

            <p className="text-xs text-gray-400">
              To review the original essay and AI justification, use the{" "}
              <strong className="text-gray-500">essay review page</strong>{" "}
              linked from the submission table above.
            </p>
          </div>

          {/* Right: resolution controls */}
          <div className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto p-6">
            {isLocked ? (
              <p className="rounded-md bg-gray-50 p-4 text-sm text-gray-600">
                This request has already been{" "}
                <strong>{request.status}</strong>.
              </p>
            ) : (
              <>
                <section aria-labelledby={`${resolveId}-action-heading`}>
                  <h3
                    id={`${resolveId}-action-heading`}
                    className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500"
                  >
                    Resolution
                  </h3>

                  {/* Resolution choice */}
                  <fieldset className="mb-4">
                    <legend className="sr-only">Choose resolution</legend>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => setResolution("approved")}
                        className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-1 ${
                          resolution === "approved"
                            ? "border-green-500 bg-green-50 text-green-700"
                            : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                        }`}
                        aria-pressed={resolution === "approved"}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => setResolution("denied")}
                        className={`flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 ${
                          resolution === "denied"
                            ? "border-red-500 bg-red-50 text-red-700"
                            : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                        }`}
                        aria-pressed={resolution === "denied"}
                      >
                        Deny
                      </button>
                    </div>
                  </fieldset>

                  {/* Approve: optional score override */}
                  {resolution === "approved" && request.criterion_score_id && (
                    <div className="mb-4">
                      <label
                        htmlFor={`${resolveId}-score`}
                        className="mb-1 block text-sm font-medium text-gray-700"
                      >
                        New criterion score{" "}
                        <span className="text-gray-400">(optional)</span>
                      </label>
                      <input
                        id={`${resolveId}-score`}
                        type="number"
                        step={1}
                        value={scoreOverride}
                        onChange={(e) => setScoreOverride(e.target.value)}
                        placeholder="Leave blank to keep current score"
                        className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    </div>
                  )}

                  {/* Deny: required resolution note */}
                  {resolution === "denied" && (
                    <div className="mb-4">
                      <label
                        htmlFor={`${resolveId}-note`}
                        className="mb-1 block text-sm font-medium text-gray-700"
                      >
                        Resolution note{" "}
                        <span className="text-red-500" aria-hidden="true">*</span>
                        <span className="sr-only">(required)</span>
                      </label>
                      <textarea
                        id={`${resolveId}-note`}
                        value={resolutionNote}
                        onChange={(e) => setResolutionNote(e.target.value)}
                        rows={4}
                        aria-required="true"
                        placeholder="Explain why the request is being denied…"
                        className="w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    </div>
                  )}

                  {/* Approve: optional note */}
                  {resolution === "approved" && (
                    <div className="mb-4">
                      <label
                        htmlFor={`${resolveId}-approve-note`}
                        className="mb-1 block text-sm font-medium text-gray-700"
                      >
                        Resolution note{" "}
                        <span className="text-gray-400">(optional)</span>
                      </label>
                      <textarea
                        id={`${resolveId}-approve-note`}
                        value={resolutionNote}
                        onChange={(e) => setResolutionNote(e.target.value)}
                        rows={3}
                        placeholder="Optional note for your records…"
                        className="w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    </div>
                  )}

                  {resolveError && (
                    <p
                      role="alert"
                      className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
                    >
                      {resolveError}
                    </p>
                  )}

                  <button
                    type="button"
                    onClick={handleResolve}
                    disabled={!resolution || resolveMutation.isPending}
                    className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {resolveMutation.isPending
                      ? "Saving…"
                      : resolution === "approved"
                        ? "Confirm approval"
                        : resolution === "denied"
                          ? "Confirm denial"
                          : "Choose a resolution"}
                  </button>
                </section>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LogRequestForm — log a regrade request for a specific essay/grade
// ---------------------------------------------------------------------------

interface LogRequestFormProps {
  essays: EssayListItem[];
  rubricCriteria: RubricSnapshotCriterion[];
  onSuccess: (created: RegradeRequest) => void;
  onCancel: () => void;
}

function LogRequestForm({
  essays,
  rubricCriteria,
  onSuccess,
  onCancel,
}: LogRequestFormProps) {
  const formId = useId();
  const [selectedEssayId, setSelectedEssayId] = useState("");
  const [selectedCriterionId, setSelectedCriterionId] = useState(""); // rubric criterion id
  const [disputeText, setDisputeText] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  // Fetch the grade for the selected essay to resolve criterion_score_ids.
  const {
    data: grade,
    isLoading: gradeLoading,
    isError: gradeError,
  } = useQuery<GradeResponse>({
    queryKey: ["grade", selectedEssayId],
    queryFn: () => getGrade(selectedEssayId),
    enabled: !!selectedEssayId,
    staleTime: 60_000,
  });

  // Map rubric_criterion_id → criterion_score_id from the loaded grade.
  // Entries without a valid rubric_criterion_id are excluded to prevent
  // incorrect map keys from null or undefined values.
  const criterionScoreMap: Record<string, string> = grade
    ? Object.fromEntries(
        grade.criterion_scores
          .filter(
            (cs): cs is typeof cs & { rubric_criterion_id: string } =>
              cs.rubric_criterion_id != null,
          )
          .map((cs) => [cs.rubric_criterion_id, cs.id]),
      )
    : {};

  const createMutation = useMutation({
    mutationFn: (body: RegradeRequestCreate) => {
      if (!grade) throw new Error("Grade not loaded");
      return createRegradeRequest(grade.id, body);
    },
    onSuccess: (created) => {
      onSuccess(created);
    },
    onError: (err) => {
      setFormError(createErrorMessage(err));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!selectedEssayId) {
      setFormError("Please select an essay.");
      return;
    }
    if (!grade && !gradeLoading) {
      setFormError("Could not load grade for the selected essay.");
      return;
    }
    if (!disputeText.trim()) {
      setFormError("Dispute text is required.");
      return;
    }

    // When a specific criterion is selected, validate that the grade has a
    // matching criterion score. Without a matching score, submitting would
    // silently log an overall-grade request instead of the intended criterion.
    if (selectedCriterionId && !criterionScoreMap[selectedCriterionId]) {
      setFormError(
        "The selected criterion was not graded for this essay. Please select a different criterion or choose 'Overall grade'.",
      );
      return;
    }

    const criterionScoreId = selectedCriterionId
      ? (criterionScoreMap[selectedCriterionId] ?? null)
      : null;

    createMutation.mutate({
      dispute_text: disputeText.trim(),
      criterion_score_id: criterionScoreId,
    });
  };

  const charsRemaining = DISPUTE_TEXT_MAX_CHARS - disputeText.length;

  // Only show essays that have a grade (status = graded, reviewed, locked, returned)
  const gradedEssays = essays.filter((e) =>
    ["graded", "reviewed", "locked", "returned"].includes(e.status),
  );

  return (
    <form
      onSubmit={handleSubmit}
      aria-label="Log regrade request"
      className="space-y-4"
    >
      {/* Essay selector */}
      <div>
        <label
          htmlFor={`${formId}-essay`}
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Essay{" "}
          <span className="text-red-500" aria-hidden="true">*</span>
        </label>
        <select
          id={`${formId}-essay`}
          value={selectedEssayId}
          onChange={(e) => {
            setSelectedEssayId(e.target.value);
            setSelectedCriterionId("");
          }}
          aria-required="true"
          className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        >
          <option value="">Select an essay…</option>
          {gradedEssays.map((essay) => (
            <option key={essay.essay_id} value={essay.essay_id}>
              {essay.student_name
                ? essay.student_name
                : `Essay ${shortId(essay.essay_id)}`}
            </option>
          ))}
        </select>
        {gradedEssays.length === 0 && (
          <p className="mt-1 text-xs text-gray-500">
            No graded essays available. Essays must be graded before logging a
            regrade request.
          </p>
        )}
      </div>

      {/* Criterion selector */}
      <div>
        <label
          htmlFor={`${formId}-criterion`}
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Criterion{" "}
          <span className="text-gray-400">(optional — leave blank for overall grade)</span>
        </label>
        {gradeLoading && selectedEssayId ? (
          <div className="h-9 w-full animate-pulse rounded-md bg-gray-200" />
        ) : (
          <select
            id={`${formId}-criterion`}
            value={selectedCriterionId}
            onChange={(e) => setSelectedCriterionId(e.target.value)}
            disabled={!selectedEssayId || gradeLoading || gradeError}
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-400"
          >
            <option value="">Overall grade</option>
            {rubricCriteria.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        )}
        {gradeError && (
          <p className="mt-1 text-xs text-red-600">
            Could not load grade data. Criterion selection is unavailable.
          </p>
        )}
      </div>

      {/* Dispute text */}
      <div>
        <label
          htmlFor={`${formId}-dispute`}
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Dispute justification{" "}
          <span className="text-red-500" aria-hidden="true">*</span>
        </label>
        <textarea
          id={`${formId}-dispute`}
          value={disputeText}
          onChange={(e) =>
            setDisputeText(e.target.value.slice(0, DISPUTE_TEXT_MAX_CHARS))
          }
          rows={4}
          aria-required="true"
          aria-describedby={`${formId}-dispute-count`}
          maxLength={DISPUTE_TEXT_MAX_CHARS}
          placeholder="Enter the justification for disputing this grade…"
          className="w-full resize-none rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <p
          id={`${formId}-dispute-count`}
          className={`mt-1 text-right text-xs ${
            charsRemaining <= 50 ? "text-red-600" : "text-gray-400"
          }`}
          aria-live="polite"
          aria-atomic="true"
        >
          {charsRemaining} character{charsRemaining !== 1 ? "s" : ""} remaining
        </p>
      </div>

      {formError && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {formError}
        </p>
      )}

      {/* Actions */}
      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={createMutation.isPending || gradeLoading}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
        >
          {createMutation.isPending ? "Submitting…" : "Submit request"}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// RegradeQueue — main component
// ---------------------------------------------------------------------------

export interface RegradeQueueProps {
  assignmentId: string;
  essays: EssayListItem[];
  /** Parsed criteria from the assignment's rubric_snapshot. */
  rubricCriteria: RubricSnapshotCriterion[];
}

export function RegradeQueue({
  assignmentId,
  essays,
  rubricCriteria,
}: RegradeQueueProps) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<"queue" | "log">("queue");
  const [selectedRequest, setSelectedRequest] = useState<RegradeRequest | null>(
    null,
  );
  const [statusFilter, setStatusFilter] = useState<
    "all" | "open" | "resolved"
  >("open");
  const [closeConfirming, setCloseConfirming] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);
  const [windowClosed, setWindowClosed] = useState(false);

  const tabId = useId();

  const {
    data: requests = [],
    isLoading,
    isError,
    refetch,
  } = useQuery<RegradeRequest[]>({
    queryKey: ["regrade-requests", assignmentId],
    queryFn: () => listRegradeRequests(assignmentId),
    enabled: !!assignmentId,
    staleTime: 30_000,
  });

  const closeMutation = useMutation({
    mutationFn: () => closeRegradeWindow(assignmentId),
    onSuccess: () => {
      setCloseConfirming(false);
      setWindowClosed(true);
      setCloseError(null);
      // Switch to queue tab — the log tab is removed when the window is closed,
      // and leaving activeTab === "log" would keep the log panel visible with
      // aria-labelledby pointing to a non-existent element.
      setActiveTab("queue");
    },
    onError: (err) => {
      setCloseError(closeWindowErrorMessage(err));
    },
  });

  const handleResolve = useCallback(
    (updated: RegradeRequest) => {
      queryClient.setQueryData<RegradeRequest[]>(
        ["regrade-requests", assignmentId],
        (prev) =>
          (prev ?? []).map((r) => (r.id === updated.id ? updated : r)),
      );
      setSelectedRequest(null);
    },
    [assignmentId, queryClient],
  );

  const handleLogSuccess = useCallback(
    (created: RegradeRequest) => {
      queryClient.setQueryData<RegradeRequest[]>(
        ["regrade-requests", assignmentId],
        // Append to keep oldest-first ordering consistent with the server response.
        (prev) => [...(prev ?? []), created],
      );
      setActiveTab("queue");
    },
    [assignmentId, queryClient],
  );

  // Arrow-key navigation between tabs (ARIA tab pattern with roving tabIndex).
  const handleTabKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    currentTab: "queue" | "log",
  ) => {
    const availableTabs = (windowClosed ? ["queue"] : ["queue", "log"]) as Array<"queue" | "log">;
    const currentIndex = availableTabs.indexOf(currentTab);
    let nextIndex = currentIndex;

    if (e.key === "ArrowRight") {
      e.preventDefault();
      nextIndex = (currentIndex + 1) % availableTabs.length;
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      nextIndex = (currentIndex - 1 + availableTabs.length) % availableTabs.length;
    } else {
      return;
    }

    const nextTab = availableTabs[nextIndex];
    setActiveTab(nextTab);
    document.getElementById(`${tabId}-${nextTab}-tab`)?.focus();
  };

  // Filtered requests
  const filteredRequests = requests.filter((r) => {
    if (statusFilter === "open") return r.status === "open";
    if (statusFilter === "resolved")
      return r.status === "approved" || r.status === "denied";
    return true;
  });

  const openCount = requests.filter((r) => r.status === "open").length;

  return (
    <section aria-labelledby={`${tabId}-heading`}>
      {/* Section heading + close window action */}
      <div className="mb-4 flex items-center justify-between">
        <h2
          id={`${tabId}-heading`}
          className="text-base font-semibold text-gray-900"
        >
          Regrade requests
          {openCount > 0 && (
            <span className="ml-2 inline-flex items-center rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700">
              {openCount} open
            </span>
          )}
        </h2>

        {/* Close regrade window */}
        {!windowClosed ? (
          <div className="flex items-center gap-2">
            {closeError && (
              <p role="alert" className="text-xs text-red-600">{closeError}</p>
            )}
            {closeConfirming ? (
              <>
                <span className="text-sm text-gray-600">
                  Close the regrade window? No new requests will be accepted.
                </span>
                {/* The Confirm button calls the mutation which calls closeRegradeWindow.
                    The stub always throws (backend endpoint not yet implemented),
                    so onError fires and shows the "coming soon" message via closeError. */}
                <button
                  type="button"
                  onClick={() => closeMutation.mutate()}
                  disabled={closeMutation.isPending}
                  className="rounded-md border border-red-300 bg-red-50 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 disabled:opacity-50"
                >
                  {closeMutation.isPending ? "Closing…" : "Confirm"}
                </button>
                <button
                  type="button"
                  onClick={() => setCloseConfirming(false)}
                  className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
                >
                  Cancel
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setCloseConfirming(true)}
                className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
              >
                Close regrade window
              </button>
            )}
          </div>
        ) : (
          <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
            Regrade window closed
          </span>
        )}
      </div>

      {/* Tabs: Queue | Log Request */}
      <div
        role="tablist"
        aria-label="Regrade request actions"
        className="mb-4 flex gap-1 border-b border-gray-200"
      >
        <button
          role="tab"
          aria-selected={activeTab === "queue"}
          aria-controls={`${tabId}-queue-panel`}
          id={`${tabId}-queue-tab`}
          tabIndex={activeTab === "queue" ? 0 : -1}
          onClick={() => setActiveTab("queue")}
          onKeyDown={(e) => handleTabKeyDown(e, "queue")}
          className={`rounded-t-md px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset ${
            activeTab === "queue"
              ? "border-b-2 border-blue-600 text-blue-600"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          Queue
        </button>
        {!windowClosed && (
          <button
            role="tab"
            aria-selected={activeTab === "log"}
            aria-controls={`${tabId}-log-panel`}
            id={`${tabId}-log-tab`}
            tabIndex={activeTab === "log" ? 0 : -1}
            onClick={() => setActiveTab("log")}
            onKeyDown={(e) => handleTabKeyDown(e, "log")}
            className={`rounded-t-md px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset ${
              activeTab === "log"
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            Log request
          </button>
        )}
      </div>

      {/* Queue tab panel */}
      <div
        role="tabpanel"
        id={`${tabId}-queue-panel`}
        aria-labelledby={`${tabId}-queue-tab`}
        hidden={activeTab !== "queue"}
      >
        {/* Status filter */}
        <div className="mb-3 flex items-center gap-2">
          <span className="text-xs font-medium text-gray-500">Show:</span>
          {(["open", "resolved", "all"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setStatusFilter(f)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 ${
                statusFilter === f
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {f === "open" ? "Open" : f === "resolved" ? "Resolved" : "All"}
            </button>
          ))}
        </div>

        {/* Loading state */}
        {isLoading && (
          <div aria-live="polite" aria-busy="true" className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 w-full animate-pulse rounded-md bg-gray-200"
              />
            ))}
          </div>
        )}

        {/* Error state */}
        {isError && !isLoading && (
          <div className="rounded-md bg-red-50 p-4">
            <p role="alert" className="text-sm text-red-700">
              Failed to load regrade requests.
            </p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="mt-2 text-sm font-medium text-red-600 underline hover:text-red-800 focus:outline-none"
            >
              Try again
            </button>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !isError && filteredRequests.length === 0 && (
          <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
            <p className="text-sm text-gray-500">
              {statusFilter === "open"
                ? "No open regrade requests."
                : statusFilter === "resolved"
                  ? "No resolved requests yet."
                  : "No regrade requests yet."}
            </p>
          </div>
        )}

        {/* Request list */}
        {!isLoading && !isError && filteredRequests.length > 0 && (
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
            <table
              className="min-w-full divide-y divide-gray-200"
              aria-label="Regrade request queue"
            >
              <thead className="bg-gray-50">
                <tr>
                  <th
                    scope="col"
                    className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                  >
                    Student / Grade
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                  >
                    Criterion
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                  >
                    Justification
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                  >
                    Status
                  </th>
                  <th
                    scope="col"
                    className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                  >
                    Date
                  </th>
                  <th scope="col" className="px-4 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredRequests.map((request) => {
                  // EssayListItem does not include grade_id; show a short
                  // request identifier as the student label. Teachers can
                  // cross-reference via the essay review page.
                  const studentLabel = `Request ${shortId(request.id)}`;

                  return (
                    <tr key={request.id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">
                        {studentLabel}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600">
                        {request.criterion_score_id
                          ? "Specific criterion"
                          : "Overall grade"}
                      </td>
                      <td className="max-w-xs px-4 py-3 text-sm text-gray-700">
                        <span className="line-clamp-2">
                          {request.dispute_text}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[request.status]}`}
                        >
                          {STATUS_LABELS[request.status]}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                        {formatDate(request.created_at)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right text-sm">
                        <button
                          type="button"
                          onClick={() => setSelectedRequest(request)}
                          className="font-medium text-blue-600 hover:text-blue-800 focus:outline-none focus:underline"
                          aria-label={`Review regrade request from ${studentLabel}`}
                        >
                          Review
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Log request tab panel — only rendered while the window is open so that
          aria-labelledby always points to the existing log tab button. */}
      {!windowClosed && (
        <div
          role="tabpanel"
          id={`${tabId}-log-panel`}
          aria-labelledby={`${tabId}-log-tab`}
          hidden={activeTab !== "log"}
        >
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
            <h3 className="mb-4 text-sm font-semibold text-gray-900">
              Log a regrade request
            </h3>
            <LogRequestForm
              essays={essays}
              rubricCriteria={rubricCriteria}
              onSuccess={handleLogSuccess}
              onCancel={() => setActiveTab("queue")}
            />
          </div>
        </div>
      )}

      {/* Review panel modal */}
      {selectedRequest && (
        <ReviewPanel
          request={selectedRequest}
          onResolve={handleResolve}
          onClose={() => setSelectedRequest(null)}
        />
      )}
    </section>
  );
}
