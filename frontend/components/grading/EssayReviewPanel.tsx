"use client";

/**
 * EssayReviewPanel — per-criterion grade review and editing.
 *
 * Features:
 * - Displays per-criterion AI score, AI justification, and feedback.
 * - Inline score override via a number input (clamped to criterion range).
 * - Inline feedback text editor (textarea).
 * - Live weighted total recalculates as the teacher types a new score.
 * - Editable overall summary feedback textarea.
 * - "Lock grade" button — requires explicit teacher action.
 * - Locked grades: ALL controls visually and functionally disabled (not hidden).
 * - Auto-saves each change on blur via PATCH API calls.
 *
 * Security:
 * - No essay content or student PII in any log or error path.
 * - API error messages are mapped to static strings; raw server text is never shown.
 * - Entity IDs only in error payloads.
 */

import { useState, useCallback, useId } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  overrideCriterionScore,
  updateFeedback,
  lockGrade,
} from "@/lib/api/grades";
import type { GradeResponse, CriterionScoreResponse } from "@/lib/api/grades";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * One criterion entry from assignment.rubric_snapshot.criteria.
 * Matches the shape produced by the backend `build_rubric_snapshot` function.
 */
export interface RubricSnapshotCriterion {
  id: string;
  name: string;
  description: string;
  weight: number;
  min_score: number;
  max_score: number;
}

// ---------------------------------------------------------------------------
// Score recalculation helper — exported for unit testing
// ---------------------------------------------------------------------------

/**
 * Compute the live total score from criterion scores and any pending local
 * score overrides the teacher has typed but not yet saved.
 *
 * Mirrors the backend formula: total_score = sum of all final_scores.
 *
 * @param criterionScores - The grade's persisted criterion scores.
 * @param localOverrides  - Map of criterionScore.id → pending teacher score.
 * @returns Live total score (integer sum).
 */
export function computeTotalScore(
  criterionScores: CriterionScoreResponse[],
  localOverrides: Record<string, number>,
): number {
  return criterionScores.reduce((sum, cs) => {
    const score =
      cs.id in localOverrides ? localOverrides[cs.id] : cs.final_score;
    return sum + score;
  }, 0);
}

// ---------------------------------------------------------------------------
// Error mapping — static strings only, never raw server messages
// ---------------------------------------------------------------------------

function criterionErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "LOCKED":
        return "This grade is locked and cannot be edited.";
      case "FORBIDDEN":
        return "You do not have permission to edit this grade.";
      case "NOT_FOUND":
        return "Grade not found. Please refresh the page.";
      case "UNPROCESSABLE_ENTITY":
        return "Score is outside the allowed range for this criterion.";
      default:
        return "Failed to save changes. Please try again.";
    }
  }
  return "Failed to save changes. Please try again.";
}

function lockErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to lock this grade.";
      case "NOT_FOUND":
        return "Grade not found. Please refresh the page.";
      default:
        return "Failed to lock grade. Please try again.";
    }
  }
  return "Failed to lock grade. Please try again.";
}

// ---------------------------------------------------------------------------
// Confidence badge
// ---------------------------------------------------------------------------

const CONFIDENCE_LABELS: Record<string, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

const CONFIDENCE_COLORS: Record<string, string> = {
  high: "bg-green-100 text-green-700",
  medium: "bg-yellow-100 text-yellow-700",
  low: "bg-red-100 text-red-700",
};

// ---------------------------------------------------------------------------
// Per-criterion card
// ---------------------------------------------------------------------------

interface CriterionCardProps {
  criterionScore: CriterionScoreResponse;
  criterion: RubricSnapshotCriterion | undefined;
  isLocked: boolean;
  gradeId: string;
  /** Called with updated grade when a save succeeds. */
  onSaveSuccess: (grade: GradeResponse) => void;
  /** Notifies the parent of the current pending score for live total calc. */
  onLocalScoreChange: (criterionScoreId: string, score: number) => void;
  /** Clears the pending local score (after save). */
  onLocalScoreClear: (criterionScoreId: string) => void;
}

function CriterionCard({
  criterionScore,
  criterion,
  isLocked,
  gradeId,
  onSaveSuccess,
  onLocalScoreChange,
  onLocalScoreClear,
}: CriterionCardProps) {
  const headingId = useId();

  const minScore = criterion?.min_score ?? 0;
  const maxScore = criterion?.max_score ?? criterionScore.ai_score;
  const criterionName = criterion?.name ?? "Unnamed criterion";

  // Local input state — tracks what the teacher has typed before blur
  const [scoreInput, setScoreInput] = useState<string>(
    String(criterionScore.final_score),
  );
  const [feedbackInput, setFeedbackInput] = useState<string>(
    criterionScore.teacher_feedback ?? criterionScore.ai_feedback ?? "",
  );

  // Error state for this criterion — static message strings only
  const [saveError, setSaveError] = useState<string | null>(null);

  const overrideMutation = useMutation({
    mutationFn: (data: { teacher_score?: number; teacher_feedback?: string }) =>
      overrideCriterionScore(gradeId, criterionScore.id, data),
    onSuccess: (updatedGrade) => {
      setSaveError(null);
      onLocalScoreClear(criterionScore.id);
      onSaveSuccess(updatedGrade);
    },
    onError: (err: unknown) => {
      setSaveError(criterionErrorMessage(err));
    },
  });

  const handleScoreBlur = useCallback(() => {
    if (isLocked) return;
    const parsed = parseInt(scoreInput, 10);
    if (isNaN(parsed)) {
      // Reset to the current final score if input is not a valid number
      setScoreInput(String(criterionScore.final_score));
      onLocalScoreClear(criterionScore.id);
      return;
    }
    const clamped = Math.max(minScore, Math.min(maxScore, parsed));
    if (String(clamped) !== scoreInput) {
      setScoreInput(String(clamped));
    }
    // Only save if the value actually changed from the persisted final_score
    if (clamped !== criterionScore.final_score) {
      overrideMutation.mutate({ teacher_score: clamped });
    } else {
      onLocalScoreClear(criterionScore.id);
    }
  }, [
    isLocked,
    scoreInput,
    criterionScore.final_score,
    criterionScore.id,
    minScore,
    maxScore,
    overrideMutation,
    onLocalScoreClear,
  ]);

  const handleFeedbackBlur = useCallback(() => {
    if (isLocked) return;
    const trimmed = feedbackInput.trim();
    const existing =
      criterionScore.teacher_feedback ?? criterionScore.ai_feedback ?? "";
    // Backend requires min_length=1 for teacher_feedback; empty strings are not sent.
    if (trimmed !== existing && trimmed.length > 0) {
      overrideMutation.mutate({ teacher_feedback: trimmed });
    }
  }, [
    isLocked,
    feedbackInput,
    criterionScore.teacher_feedback,
    criterionScore.ai_feedback,
    overrideMutation,
  ]);

  const isSaving = overrideMutation.isPending;

  return (
    <article
      aria-labelledby={headingId}
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      {/* Criterion header */}
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <h3 id={headingId} className="text-sm font-semibold text-gray-900">
          {criterionName}
          {criterion && (
            <span className="ml-2 text-xs font-normal text-gray-400">
              (weight: {criterion.weight}%)
            </span>
          )}
        </h3>
        {/* Confidence badge */}
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
            CONFIDENCE_COLORS[criterionScore.confidence] ??
            "bg-gray-100 text-gray-600"
          }`}
          aria-label={
            CONFIDENCE_LABELS[criterionScore.confidence] ?? "Unknown confidence"
          }
        >
          {criterionScore.confidence}
        </span>
      </div>

      {/* AI justification */}
      <p className="mb-3 text-xs text-gray-500">
        <span className="font-medium text-gray-700">AI justification: </span>
        {criterionScore.ai_justification}
      </p>

      {/* Score row */}
      <div className="mb-3 flex flex-wrap items-center gap-4">
        <div>
          <span className="text-xs text-gray-500">AI score: </span>
          <span className="font-semibold text-gray-900">
            {criterionScore.ai_score}
          </span>
          <span className="text-xs text-gray-400"> / {maxScore}</span>
        </div>

        {/* Teacher score override */}
        <div className="flex items-center gap-2">
          <label
            htmlFor={`score-${criterionScore.id}`}
            className="text-xs text-gray-500"
          >
            Your score:
          </label>
          <input
            id={`score-${criterionScore.id}`}
            type="number"
            min={minScore}
            max={maxScore}
            step={1}
            value={scoreInput}
            disabled={isLocked}
            aria-label={`Override score for ${criterionName} (${minScore}–${maxScore})`}
            aria-describedby={saveError ? `score-error-${criterionScore.id}` : undefined}
            onChange={(e) => {
              setScoreInput(e.target.value);
              const parsed = parseInt(e.target.value, 10);
              if (!isNaN(parsed)) {
                // Clamp immediately so the live total never shows an out-of-range value.
                const clamped = Math.max(minScore, Math.min(maxScore, parsed));
                onLocalScoreChange(criterionScore.id, clamped);
              }
            }}
            onBlur={handleScoreBlur}
            className="w-16 rounded-md border border-gray-300 px-2 py-1 text-center text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:opacity-60"
          />
          <span className="text-xs text-gray-400">/ {maxScore}</span>
          {isSaving && (
            <span className="text-xs text-gray-400" aria-live="polite">
              Saving…
            </span>
          )}
        </div>
      </div>

      {/* Save error */}
      {saveError && (
        <p
          id={`score-error-${criterionScore.id}`}
          role="alert"
          className="mb-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700"
        >
          {saveError}
        </p>
      )}

      {/* Feedback textarea */}
      <div>
        <label
          htmlFor={`feedback-${criterionScore.id}`}
          className="mb-1 block text-xs font-medium text-gray-700"
        >
          Feedback
        </label>
        <textarea
          id={`feedback-${criterionScore.id}`}
          rows={3}
          disabled={isLocked}
          aria-label={`Feedback for ${criterionName}`}
          value={feedbackInput}
          onChange={(e) => setFeedbackInput(e.target.value)}
          onBlur={handleFeedbackBlur}
          placeholder={isLocked ? "" : "Add feedback for this criterion…"}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:opacity-60"
        />
      </div>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface EssayReviewPanelProps {
  /** The current grade returned by GET /essays/{essayId}/grade. */
  grade: GradeResponse;
  /**
   * Criteria from assignment.rubric_snapshot.criteria.
   * Used to look up criterion names, weights, and score ranges.
   */
  criteria: RubricSnapshotCriterion[];
  /**
   * Called when any save operation returns an updated grade.
   * The parent should update its own grade state and any affected query caches.
   */
  onGradeUpdate: (grade: GradeResponse) => void;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function EssayReviewPanel({
  grade,
  criteria,
  onGradeUpdate,
}: EssayReviewPanelProps) {
  // Local pending score overrides — used for live total recalculation
  // before changes are saved to the server.
  const [localScoreOverrides, setLocalScoreOverrides] = useState<
    Record<string, number>
  >({});

  // Summary feedback local state
  const [summaryFeedback, setSummaryFeedback] = useState<string>(
    grade.summary_feedback_edited ?? grade.summary_feedback,
  );
  const [summaryFeedbackError, setSummaryFeedbackError] = useState<
    string | null
  >(null);

  // Lock error
  const [lockError, setLockError] = useState<string | null>(null);

  const isLocked = grade.is_locked;

  // Build a map from rubric_criterion_id → criterion for O(1) lookup
  const criteriaMap = new Map<string, RubricSnapshotCriterion>(
    criteria.map((c) => [c.id, c]),
  );

  // Live total score calculation
  const liveTotal = computeTotalScore(grade.criterion_scores, localScoreOverrides);

  const handleLocalScoreChange = useCallback(
    (criterionScoreId: string, score: number) => {
      setLocalScoreOverrides((prev) => ({ ...prev, [criterionScoreId]: score }));
    },
    [],
  );

  const handleLocalScoreClear = useCallback((criterionScoreId: string) => {
    setLocalScoreOverrides((prev) => {
      const next = { ...prev };
      delete next[criterionScoreId];
      return next;
    });
  }, []);

  const handleCriterionSaveSuccess = useCallback(
    (updatedGrade: GradeResponse) => {
      onGradeUpdate(updatedGrade);
    },
    [onGradeUpdate],
  );

  // Summary feedback mutation
  const feedbackMutation = useMutation({
    mutationFn: (text: string) =>
      updateFeedback(grade.id, { summary_feedback: text }),
    onSuccess: (updatedGrade) => {
      setSummaryFeedbackError(null);
      onGradeUpdate(updatedGrade);
    },
    onError: (err: unknown) => {
      setSummaryFeedbackError(criterionErrorMessage(err));
    },
  });

  const handleSummaryFeedbackBlur = useCallback(() => {
    if (isLocked) return;
    const trimmed = summaryFeedback.trim();
    const existing =
      grade.summary_feedback_edited ?? grade.summary_feedback;
    // Backend PatchFeedbackRequest requires min_length=1 for summary_feedback;
    // empty strings are not sent to avoid a 422 validation error.
    if (trimmed !== existing && trimmed.length > 0) {
      feedbackMutation.mutate(trimmed);
    }
  }, [
    isLocked,
    summaryFeedback,
    grade.summary_feedback_edited,
    grade.summary_feedback,
    feedbackMutation,
  ]);

  // Lock mutation
  const lockMutation = useMutation({
    mutationFn: () => lockGrade(grade.id),
    onSuccess: (updatedGrade) => {
      setLockError(null);
      onGradeUpdate(updatedGrade);
    },
    onError: (err: unknown) => {
      setLockError(lockErrorMessage(err));
    },
  });

  return (
    <section aria-label="Grade review" className="space-y-4">
      {/* Total score banner */}
      <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
              Total score
            </span>
            <p
              className="text-2xl font-bold text-gray-900"
              aria-live="polite"
              aria-atomic="true"
              aria-label={`Total score: ${liveTotal} out of ${grade.max_possible_score}`}
            >
              {liveTotal}
              <span className="ml-1 text-base font-normal text-gray-500">
                / {grade.max_possible_score}
              </span>
            </p>
          </div>

          {isLocked && (
            <span
              className="inline-flex items-center rounded-full bg-green-100 px-3 py-1 text-xs font-medium text-green-700"
              aria-label="This grade is locked"
            >
              Locked
            </span>
          )}
        </div>
      </div>

      {/* Summary feedback */}
      <div>
        <label
          htmlFor="summary-feedback"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Overall feedback
        </label>
        <textarea
          id="summary-feedback"
          rows={4}
          disabled={isLocked}
          aria-label="Overall summary feedback"
          aria-describedby={
            summaryFeedbackError ? "summary-feedback-error" : undefined
          }
          value={summaryFeedback}
          onChange={(e) => setSummaryFeedback(e.target.value)}
          onBlur={handleSummaryFeedbackBlur}
          placeholder={isLocked ? "" : "Add or edit the overall feedback…"}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:opacity-60"
        />
        {summaryFeedbackError && (
          <p
            id="summary-feedback-error"
            role="alert"
            className="mt-1 text-xs text-red-700"
          >
            {summaryFeedbackError}
          </p>
        )}
        {feedbackMutation.isPending && (
          <p className="mt-1 text-xs text-gray-400" aria-live="polite">
            Saving…
          </p>
        )}
      </div>

      {/* Per-criterion cards */}
      {grade.criterion_scores.map((cs) => (
        <CriterionCard
          key={cs.id}
          criterionScore={cs}
          criterion={criteriaMap.get(cs.rubric_criterion_id)}
          isLocked={isLocked}
          gradeId={grade.id}
          onSaveSuccess={handleCriterionSaveSuccess}
          onLocalScoreChange={handleLocalScoreChange}
          onLocalScoreClear={handleLocalScoreClear}
        />
      ))}

      {/* Lock grade */}
      <div className="border-t border-gray-200 pt-4">
        {lockError && (
          <p role="alert" className="mb-3 text-sm text-red-700">
            {lockError}
          </p>
        )}
        <button
          type="button"
          disabled={isLocked || lockMutation.isPending}
          onClick={() => lockMutation.mutate()}
          aria-label={
            isLocked
              ? "Grade is already locked"
              : "Lock this grade as final — no further edits will be allowed"
          }
          className="w-full rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLocked
            ? "Grade locked"
            : lockMutation.isPending
              ? "Locking…"
              : "Lock grade"}
        </button>
        {isLocked && (
          <p className="mt-2 text-center text-xs text-gray-500">
            Locked
            {grade.locked_at
              ? ` on ${new Date(grade.locked_at).toLocaleDateString()}`
              : ""}
            . No further edits are allowed.
          </p>
        )}
      </div>
    </section>
  );
}
