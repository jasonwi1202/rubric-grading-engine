"use client";

/**
 * RecommendationPanel — Instruction recommendation review UI (M6-09).
 *
 * Displays AI-generated instruction recommendation sets for a student.
 * Supports:
 *   - Listing existing recommendation sets (GET /students/{id}/recommendations)
 *   - Generating new recommendations (POST /students/{id}/recommendations)
 *   - Per-card: accept (explicit confirmation dialog), modify (inline edit +
 *     confirmation), and dismiss actions
 *   - UI disabled while mutations are pending
 *
 * Each recommendation card shows:
 *   - Objective (activity title)
 *   - Structure (strategy type, estimated duration, description)
 *   - Evidence summary (skill gaps that triggered the recommendation)
 *
 * Security:
 *   - No student PII in query keys — entity IDs only.
 *   - Error messages are static strings; raw server text is never rendered.
 *   - No student data written to localStorage or sessionStorage.
 */

import { useState, useId, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listStudentRecommendations,
  generateStudentRecommendations,
  assignRecommendation,
  dismissRecommendation,
} from "@/lib/api/recommendations";
import type {
  InstructionRecommendationResponse,
  RecommendationItemResponse,
  RecommendationStatus,
} from "@/lib/api/recommendations";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STRATEGY_LABELS: Record<string, string> = {
  mini_lesson: "Mini-lesson",
  guided_practice: "Guided Practice",
  independent_practice: "Independent Practice",
  intervention: "Intervention",
};

const STATUS_LABELS: Record<RecommendationStatus, string> = {
  pending_review: "Pending Review",
  accepted: "Accepted",
  dismissed: "Dismissed",
};

const STATUS_BADGE_CLASSES: Record<RecommendationStatus, string> = {
  pending_review: "bg-yellow-50 text-yellow-800 ring-1 ring-yellow-200",
  accepted: "bg-green-50 text-green-700 ring-1 ring-green-200",
  dismissed: "bg-gray-100 text-gray-500 ring-1 ring-gray-200",
};

const GRADE_LEVEL_OPTIONS = [
  "Grade 3",
  "Grade 4",
  "Grade 5",
  "Grade 6",
  "Grade 7",
  "Grade 8",
  "Grade 9",
  "Grade 10",
  "Grade 11",
  "Grade 12",
];

const DEFAULT_DURATION_MINUTES = 20;
const MIN_DURATION_MINUTES = 5;
const MAX_DURATION_MINUTES = 120;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function strategyLabel(strategy: string): string {
  return STRATEGY_LABELS[strategy] ?? strategy.replace(/_/g, " ");
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return "Recommendation not found.";
    if (err.status === 409) return "This recommendation cannot be updated — it may already be assigned or dismissed.";
  }
  return "An error occurred. Please try again.";
}

/** Clamp a raw numeric input value to the allowed duration range. */
function clampDuration(value: number): number {
  if (Number.isNaN(value) || value < MIN_DURATION_MINUTES) return MIN_DURATION_MINUTES;
  if (value > MAX_DURATION_MINUTES) return MAX_DURATION_MINUTES;
  return value;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/**
 * A single activity item within a recommendation set.
 */
function ActivityItem({ item }: { item: RecommendationItemResponse }) {
  return (
    <div className="rounded-md border border-gray-100 bg-gray-50 p-3">
      {/* Objective / title */}
      <div className="flex flex-wrap items-start gap-2">
        <h4 className="font-medium text-gray-900 text-sm">{item.title}</h4>
        <span className="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-100">
          {strategyLabel(item.strategy_type)}
        </span>
        <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
          ~{item.estimated_minutes} min
        </span>
      </div>
      {/* Skill dimension */}
      <p className="mt-0.5 text-xs font-medium capitalize text-purple-700">
        Skill: {item.skill_dimension.replace(/_/g, " ")}
      </p>
      {/* Structure / description */}
      <p className="mt-2 text-sm text-gray-700 leading-relaxed whitespace-pre-line">
        {item.description}
      </p>
    </div>
  );
}

/**
 * Editable version of an activity item for the "modify" flow.
 */
function ActivityItemEditable({
  item,
  index,
  cardId,
  onChangeTitle,
  onChangeDescription,
  disabled,
}: {
  item: RecommendationItemResponse;
  index: number;
  cardId: string;
  onChangeTitle: (index: number, value: string) => void;
  onChangeDescription: (index: number, value: string) => void;
  disabled: boolean;
}) {
  return (
    <div className="rounded-md border border-blue-100 bg-blue-50 p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-200">
          {strategyLabel(item.strategy_type)}
        </span>
        <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
          ~{item.estimated_minutes} min
        </span>
        <span className="shrink-0 text-xs font-medium capitalize text-purple-700">
          Skill: {item.skill_dimension.replace(/_/g, " ")}
        </span>
      </div>
      <div>
        <label
          htmlFor={`${cardId}-edit-title-${index}`}
          className="block text-xs font-medium text-gray-600 mb-1"
        >
          Objective
        </label>
        <input
          id={`${cardId}-edit-title-${index}`}
          type="text"
          value={item.title}
          onChange={(e) => onChangeTitle(index, e.target.value)}
          disabled={disabled}
          maxLength={200}
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:opacity-60"
        />
      </div>
      <div>
        <label
          htmlFor={`${cardId}-edit-desc-${index}`}
          className="block text-xs font-medium text-gray-600 mb-1"
        >
          Structure / description
        </label>
        <textarea
          id={`${cardId}-edit-desc-${index}`}
          value={item.description}
          onChange={(e) => onChangeDescription(index, e.target.value)}
          disabled={disabled}
          maxLength={5000}
          rows={4}
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:opacity-60 resize-y"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confirm dialog — focus-trapped, Escape closes it
// ---------------------------------------------------------------------------

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  isPending: boolean;
  isDestructive?: boolean;
  /** Element that triggered the dialog; receives focus when the dialog closes. */
  triggerRef?: React.RefObject<HTMLButtonElement | null>;
}

function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
  isPending,
  isDestructive = false,
  triggerRef,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  // Move focus into the dialog on open; restore to trigger element on unmount.
  useEffect(() => {
    // Capture the trigger at mount time; the ref may have changed by cleanup.
    const trigger = triggerRef?.current ?? null;
    cancelRef.current?.focus();
    return () => {
      trigger?.focus();
    };
  // triggerRef is a stable ref object — its identity never changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Trap focus within the dialog and close on Escape.
  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
      return;
    }
    if (e.key === "Tab" && dialogRef.current) {
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex=\"-1\"])",
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
  }

  const confirmClass = isDestructive
    ? "bg-red-600 text-white hover:bg-red-700 focus:ring-red-500"
    : "bg-blue-600 text-white hover:bg-blue-700 focus:ring-blue-500";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onKeyDown={handleKeyDown}
    >
      <div ref={dialogRef} className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 shadow-xl">
        <h2 id={titleId} className="mb-2 text-base font-semibold text-gray-900">
          {title}
        </h2>
        <p className="mb-5 text-sm text-gray-600">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            disabled={isPending}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-1 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className={`rounded-md px-3 py-1.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-offset-1 disabled:opacity-50 ${confirmClass}`}
          >
            {isPending ? "Please wait…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RecommendationCard
// ---------------------------------------------------------------------------

type CardMode = "view" | "modify" | "confirm-accept" | "confirm-dismiss";

interface RecommendationCardProps {
  rec: InstructionRecommendationResponse;
  onAssigned: () => void;
  onDismissed: () => void;
  anyPending: boolean;
  onPendingChange: (isPending: boolean) => void;
}

function RecommendationCard({
  rec,
  onAssigned,
  onDismissed,
  anyPending,
  onPendingChange,
}: RecommendationCardProps) {
  const [mode, setMode] = useState<CardMode>("view");
  // Track which mode triggered the accept confirmation so Cancel restores correctly.
  // "view" → Accept opens confirm from view mode; Cancel → view
  // "modify" → "Assign" opens confirm from modify mode; Cancel → modify
  const [preConfirmMode, setPreConfirmMode] = useState<"view" | "modify">("view");
  const [editedItems, setEditedItems] = useState<RecommendationItemResponse[]>(
    rec.recommendations,
  );

  const headingId = useId();
  const cardId = useId();

  // Refs for trigger buttons — used to restore focus when dialogs close.
  const acceptBtnRef = useRef<HTMLButtonElement>(null);
  const dismissBtnRef = useRef<HTMLButtonElement>(null);
  const assignModifiedBtnRef = useRef<HTMLButtonElement>(null);

  const assignMutation = useMutation({
    mutationFn: () => assignRecommendation(rec.id),
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: () => {
      setMode("view");
      onAssigned();
    },
  });

  const dismissMutation = useMutation({
    mutationFn: () => dismissRecommendation(rec.id),
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: () => {
      setMode("view");
      onDismissed();
    },
  });

  const isPending = assignMutation.isPending || dismissMutation.isPending;
  const isTerminal = rec.status === "accepted" || rec.status === "dismissed";

  function handleChangeTitle(index: number, value: string) {
    setEditedItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, title: value } : item)),
    );
  }

  function handleChangeDescription(index: number, value: string) {
    setEditedItems((prev) =>
      prev.map((item, i) =>
        i === index ? { ...item, description: value } : item,
      ),
    );
  }

  function handleCancelEdit() {
    setEditedItems(rec.recommendations);
    setMode("view");
  }

  const created = new Date(rec.created_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  return (
    <li
      className="rounded-lg border border-gray-200 bg-white shadow-sm"
      aria-labelledby={headingId}
    >
      <div className="px-5 py-4">
        {/* Header row */}
        <div className="mb-3 flex flex-wrap items-start gap-2">
          <h3 id={headingId} className="font-semibold text-gray-900">
            {rec.skill_key
              ? `${rec.skill_key.replace(/_/g, " ")} recommendations`
              : "General recommendations"}
          </h3>
          <span
            className={`ml-auto shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_BADGE_CLASSES[rec.status]}`}
          >
            {STATUS_LABELS[rec.status]}
          </span>
        </div>

        {/* Meta */}
        <p className="mb-1 text-xs text-gray-400">
          Grade level: {rec.grade_level} · Generated {created}
        </p>

        {/* Evidence summary */}
        <section aria-label="Evidence summary" className="mb-4">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Evidence summary
          </h4>
          <p className="rounded-md border border-gray-100 bg-amber-50 px-3 py-2 text-sm text-gray-700 leading-relaxed">
            {rec.evidence_summary}
          </p>
        </section>

        {/* Activity items */}
        {rec.recommendations.length === 0 ? (
          <p className="text-sm text-gray-400 italic">
            No specific activities generated. Try regenerating.
          </p>
        ) : (
          <section aria-label="Recommended activities" className="mb-4">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Recommended activities
            </h4>
            <ul className="space-y-2" role="list">
              {mode === "modify"
                ? editedItems.map((item, i) => (
                    <li key={i}>
                      <ActivityItemEditable
                        item={item}
                        index={i}
                        cardId={cardId}
                        onChangeTitle={handleChangeTitle}
                        onChangeDescription={handleChangeDescription}
                        disabled={isPending}
                      />
                    </li>
                  ))
                : rec.recommendations.map((item, i) => (
                    <li key={i}>
                      <ActivityItem item={item} />
                    </li>
                  ))}
            </ul>
          </section>
        )}

        {/* Mutation error feedback */}
        {assignMutation.isError && (
          <p role="alert" className="mb-3 text-xs text-red-600">
            {errorMessage(assignMutation.error)}
          </p>
        )}
        {dismissMutation.isError && (
          <p role="alert" className="mb-3 text-xs text-red-600">
            {errorMessage(dismissMutation.error)}
          </p>
        )}

        {/* Action controls — hidden for terminal states */}
        {!isTerminal && (
          <div className="flex flex-wrap gap-2">
            {mode === "view" && (
              <>
                <button
                  ref={acceptBtnRef}
                  type="button"
                  onClick={() => {
                    setPreConfirmMode("view");
                    setMode("confirm-accept");
                  }}
                  disabled={anyPending || isPending}
                  className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Accept
                </button>
                <button
                  type="button"
                  onClick={() => setMode("modify")}
                  disabled={anyPending || isPending}
                  className="rounded-md border border-blue-300 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Modify
                </button>
                <button
                  ref={dismissBtnRef}
                  type="button"
                  onClick={() => setMode("confirm-dismiss")}
                  disabled={anyPending || isPending}
                  className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Dismiss
                </button>
              </>
            )}

            {mode === "modify" && (
              <>
                <p className="w-full mb-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                  Edits above are for your planning reference and are not saved to the record.
                </p>
                <button
                  ref={assignModifiedBtnRef}
                  type="button"
                  onClick={() => {
                    setPreConfirmMode("modify");
                    setMode("confirm-accept");
                  }}
                  disabled={isPending}
                  className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Assign
                </button>
                <button
                  type="button"
                  onClick={handleCancelEdit}
                  disabled={isPending}
                  className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Confirmation dialogs — rendered outside the card's scroll context */}
      {mode === "confirm-accept" && (
        <ConfirmDialog
          title="Assign this recommendation?"
          message="This recommendation will be recorded as assigned. This action cannot be undone."
          confirmLabel="Confirm assignment"
          onConfirm={() => assignMutation.mutate()}
          onCancel={() => setMode(preConfirmMode)}
          isPending={isPending}
          triggerRef={preConfirmMode === "modify" ? assignModifiedBtnRef : acceptBtnRef}
        />
      )}

      {mode === "confirm-dismiss" && (
        <ConfirmDialog
          title="Dismiss this recommendation?"
          message="The recommendation will be marked as dismissed and removed from your active queue."
          confirmLabel="Dismiss"
          onConfirm={() => dismissMutation.mutate()}
          onCancel={() => setMode("view")}
          isPending={isPending}
          isDestructive
          triggerRef={dismissBtnRef}
        />
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Generate form
// ---------------------------------------------------------------------------

interface GenerateFormProps {
  studentId: string;
  onGenerated: () => void;
}

function GenerateForm({ studentId, onGenerated }: GenerateFormProps) {
  const [gradeLevel, setGradeLevel] = useState(GRADE_LEVEL_OPTIONS[5]); // Grade 8 default
  const [durationMinutes, setDurationMinutes] = useState(DEFAULT_DURATION_MINUTES);
  const formId = useId();

  const generateMutation = useMutation({
    mutationFn: () =>
      generateStudentRecommendations(studentId, {
        grade_level: gradeLevel,
        duration_minutes: durationMinutes,
      }),
    onSuccess: () => {
      onGenerated();
    },
  });

  return (
    <form
      aria-labelledby={`${formId}-heading`}
      onSubmit={(e) => {
        e.preventDefault();
        generateMutation.mutate();
      }}
      className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4"
    >
      <h3
        id={`${formId}-heading`}
        className="mb-3 text-sm font-semibold text-gray-800"
      >
        Generate new recommendations
      </h3>

      <div className="flex flex-wrap items-end gap-3">
        {/* Grade level */}
        <div>
          <label
            htmlFor={`${formId}-grade`}
            className="block text-xs font-medium text-gray-600 mb-1"
          >
            Grade level
          </label>
          <select
            id={`${formId}-grade`}
            value={gradeLevel}
            onChange={(e) => setGradeLevel(e.target.value)}
            disabled={generateMutation.isPending}
            className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
          >
            {GRADE_LEVEL_OPTIONS.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </div>

        {/* Duration */}
        <div>
          <label
            htmlFor={`${formId}-duration`}
            className="block text-xs font-medium text-gray-600 mb-1"
          >
            Target duration (min)
          </label>
          <input
            id={`${formId}-duration`}
            type="number"
            min={MIN_DURATION_MINUTES}
            max={MAX_DURATION_MINUTES}
            step={1}
            value={durationMinutes}
            onChange={(e) => {
              const n = e.currentTarget.valueAsNumber;
              if (Number.isInteger(n)) {
                setDurationMinutes(n);
              }
            }}
            onBlur={(e) => {
              const n = e.currentTarget.valueAsNumber;
              setDurationMinutes(
                clampDuration(Number.isInteger(n) ? n : durationMinutes),
              );
            }}
            disabled={generateMutation.isPending}
            className="w-24 rounded border border-gray-300 px-2 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
          />
        </div>

        <button
          type="submit"
          disabled={generateMutation.isPending}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {generateMutation.isPending ? "Generating…" : "Generate"}
        </button>
      </div>

      {generateMutation.isError && (
        <p role="alert" className="mt-2 text-xs text-red-600">
          Failed to generate recommendations. Please try again.
        </p>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface RecommendationPanelProps {
  /** Student ID (UUID) whose recommendations to load and display. */
  studentId: string;
}

/**
 * Displays instruction recommendation sets for a student.
 * Includes a generate form, recommendation cards with accept/modify/dismiss,
 * and explicit confirmation before any mutation is applied.
 */
export function RecommendationPanel({ studentId }: RecommendationPanelProps) {
  const queryClient = useQueryClient();
  // Track how many cards currently have a mutation in-flight.
  // When > 0, all cards disable their action buttons.
  const [pendingCount, setPendingCount] = useState(0);
  const anyPending = pendingCount > 0;

  const { data: recs, isLoading, isError } = useQuery({
    queryKey: ["student-recommendations", studentId],
    queryFn: () => listStudentRecommendations(studentId),
    enabled: !!studentId,
  });

  function invalidate() {
    void queryClient.invalidateQueries({
      queryKey: ["student-recommendations", studentId],
    });
  }

  function handlePendingChange(isPending: boolean) {
    setPendingCount((n) => Math.max(0, isPending ? n + 1 : n - 1));
  }

  if (isLoading) {
    return (
      <div aria-live="polite" aria-busy="true" className="space-y-3">
        {[1, 2].map((i) => (
          <div key={i} className="h-40 animate-pulse rounded-lg bg-gray-200" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <p
        role="alert"
        className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        Failed to load recommendations. Please refresh the page.
      </p>
    );
  }

  const allRecs = recs ?? [];
  // Show pending-review first, then accepted, then dismissed.
  const sorted = [...allRecs].sort((a, b) => {
    const order: Record<RecommendationStatus, number> = {
      pending_review: 0,
      accepted: 1,
      dismissed: 2,
    };
    return order[a.status] - order[b.status];
  });

  return (
    <div className="space-y-4">
      {/* Generate form */}
      <GenerateForm studentId={studentId} onGenerated={invalidate} />

      {/* Recommendation list */}
      {allRecs.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
          <p className="text-sm font-medium text-gray-700">
            No recommendations yet.
          </p>
          <p className="mt-1 text-xs text-gray-500">
            Use the form above to generate AI-powered instructional recommendations
            based on this student&rsquo;s skill profile.
          </p>
        </div>
      ) : (
        <ul className="space-y-3" role="list" aria-label="Instruction recommendations">
          {sorted.map((rec) => (
            <RecommendationCard
              key={rec.id}
              rec={rec}
              onAssigned={invalidate}
              onDismissed={invalidate}
              anyPending={anyPending}
              onPendingChange={handlePendingChange}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
