"use client";

/**
 * RubricBuilderForm — full-featured rubric builder.
 *
 * Features:
 * - Criterion list with add, edit, delete, and reorder (drag-and-drop +
 *   keyboard-accessible up/down buttons).
 * - Per-criterion fields: name, description, weight, min_score, max_score,
 *   and anchor descriptions (score-level exemplars).
 * - Live weight-sum indicator — red when the total is not 100%.
 * - Save/cancel with an unsaved-changes guard (beforeunload + confirmation).
 * - Template picker — load from a system or personal template (pre-fills form,
 *   does not auto-save).
 * - React Hook Form + Zod validation.
 * - All API calls through lib/api/client.ts (via lib/api/rubrics.ts).
 *
 * Security: no student PII is handled in this component.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  useForm,
  useFieldArray,
  useWatch,
  Controller,
} from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import type {
  AnchorDescriptions,
} from "@/lib/api/rubrics";
import { TemplatePicker } from "@/components/rubric/TemplatePicker";
import type { TemplateApplyValues } from "@/components/rubric/TemplatePicker";
import { convertApiCriteriaToForm } from "@/components/rubric/rubricFormUtils";

// ---------------------------------------------------------------------------
// Zod schema
// ---------------------------------------------------------------------------

const anchorSchema = z.record(z.string(), z.string());

export const criterionSchema = z
  .object({
    name: z
      .string()
      .min(1, "Criterion name is required")
      .max(255, "Criterion name is too long"),
    description: z.string().max(2000, "Description is too long"),
    weight: z
      .number()
      .min(0.01, "Weight must be greater than 0")
      .max(100, "Weight cannot exceed 100"),
    min_score: z
      .number()
      .int("Min score must be a whole number")
      .min(1, "Min score must be at least 1"),
    max_score: z
      .number()
      .int("Max score must be a whole number")
      .min(1, "Max score must be at least 1"),
    anchor_descriptions: anchorSchema,
  })
  .refine((criterion) => criterion.max_score > criterion.min_score, {
    message: "Max score must be greater than min score",
    path: ["max_score"],
  });

export const rubricFormSchema = z
  .object({
    name: z
      .string()
      .min(1, "Rubric name is required")
      .max(255, "Rubric name is too long"),
    criteria: z
      .array(criterionSchema)
      .min(1, "At least one criterion is required")
      .max(8, "A rubric may have at most 8 criteria"),
  })
  .refine(
    (data) => {
      const total = data.criteria.reduce(
        (sum, c) => sum + (Number.isFinite(c.weight) ? c.weight : 0),
        0,
      );
      // Round to 2dp to match the backend's Numeric(5,2) quantization, then
      // compare exactly to 100 (same rule the API enforces).
      return Math.round(total * 100) / 100 === 100;
    },
    {
      message: "Criterion weights must sum to 100%",
      path: ["criteria"],
    },
  );

export type RubricFormValues = z.infer<typeof rubricFormSchema>;

/** Default number of criteria rows shown in a new rubric. */
const DEFAULT_CRITERION_COUNT = 3;

// ---------------------------------------------------------------------------
// Helper — build empty criterion
// ---------------------------------------------------------------------------

export function createEmptyCriterion(order: number): RubricFormValues["criteria"][number] {
  return {
    name: `Criterion ${order}`,
    description: "",
    weight: 0,
    min_score: 1,
    max_score: 5,
    anchor_descriptions: {},
  };
}

// ---------------------------------------------------------------------------
// Helper — compute weight sum
// ---------------------------------------------------------------------------

export function computeWeightSum(
  criteria: Array<{ weight: number }>,
): number {
  return criteria.reduce(
    (sum, c) => sum + (Number.isFinite(c.weight) ? c.weight : 0),
    0,
  );
}

// ---------------------------------------------------------------------------
// WeightSumIndicator sub-component
// ---------------------------------------------------------------------------

interface WeightSumIndicatorProps {
  sum: number;
}

export function WeightSumIndicator({ sum }: WeightSumIndicatorProps) {
  // Round to 2dp to match the backend's Numeric(5,2) rule used in validation.
  const rounded2dp = Math.round(sum * 100) / 100;
  const isValid = rounded2dp === 100;
  // Display with up to 2 decimal places (drop trailing zeros for readability).
  const displayPct = Number.isInteger(rounded2dp)
    ? String(rounded2dp)
    : rounded2dp.toFixed(2).replace(/\.?0+$/, "");

  return (
    <p
      role="status"
      aria-live="polite"
      className={`text-sm font-medium ${isValid ? "text-green-700" : "text-red-600"}`}
      data-testid="weight-sum-indicator"
    >
      Weight total:{" "}
      <span className={isValid ? "text-green-700" : "text-red-600"}>
        {displayPct}%
      </span>{" "}
      {isValid ? "✓" : "(must equal 100%)"}
    </p>
  );
}

// ---------------------------------------------------------------------------
// CriterionRow sub-component
// ---------------------------------------------------------------------------

interface CriterionRowProps {
  index: number;
  total: number;
  isSubmitting: boolean;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  /** React Hook Form field name prefix */
  fieldPrefix: `criteria.${number}`;
  /** Bound register/control from parent */
  register: ReturnType<typeof useForm<RubricFormValues>>["register"];
  control: ReturnType<typeof useForm<RubricFormValues>>["control"];
  errors: ReturnType<
    typeof useForm<RubricFormValues>
  >["formState"]["errors"]["criteria"];
  /** Drag-and-drop handlers */
  onDragStart: (e: React.DragEvent<HTMLDivElement>) => void;
  onDragOver: (e: React.DragEvent<HTMLDivElement>) => void;
  onDrop: (e: React.DragEvent<HTMLDivElement>) => void;
  onDragEnd: () => void;
  isDragOver: boolean;
}

function CriterionRow({
  index,
  total,
  isSubmitting,
  isExpanded,
  onToggleExpand,
  onMoveUp,
  onMoveDown,
  onRemove,
  fieldPrefix,
  register,
  control,
  errors,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  isDragOver,
}: CriterionRowProps) {
  const criterionErrors = errors?.[index];

  // Watch anchor_descriptions and min/max to render score slots
  const minScore = useWatch({ control, name: `${fieldPrefix}.min_score` });
  const maxScore = useWatch({ control, name: `${fieldPrefix}.max_score` });

  const scoreRange: number[] = [];
  if (
    Number.isFinite(minScore) &&
    Number.isFinite(maxScore) &&
    maxScore >= minScore &&
    maxScore - minScore <= 9 // guard against huge ranges
  ) {
    for (let s = Number(minScore); s <= Number(maxScore); s++) {
      scoreRange.push(s);
    }
  }

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      className={`rounded-lg border bg-white transition-colors ${
        isDragOver
          ? "border-blue-400 bg-blue-50"
          : "border-gray-200"
      }`}
      aria-label={`Criterion ${index + 1}`}
    >
      {/* Criterion header row */}
      <div className="flex items-center gap-2 px-3 py-2">
        {/* Drag handle — decorative only because keyboard reordering is
            provided by the up/down buttons below */}
        <span
          className="cursor-grab text-gray-400 hover:text-gray-600 select-none"
          aria-hidden="true"
          title="Drag to reorder"
        >
          ⠿
        </span>

        {/* Up / Down buttons for keyboard reorder */}
        <div className="flex flex-col gap-0.5">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={index === 0 || isSubmitting}
            aria-label={`Move criterion ${index + 1} up`}
            className="rounded p-0.5 text-gray-400 hover:text-gray-700 disabled:opacity-30 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            ▲
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={index === total - 1 || isSubmitting}
            aria-label={`Move criterion ${index + 1} down`}
            className="rounded p-0.5 text-gray-400 hover:text-gray-700 disabled:opacity-30 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            ▼
          </button>
        </div>

        {/* Name field */}
        <div className="flex-1 min-w-0">
          <label htmlFor={`${fieldPrefix}-name`} className="sr-only">
            Criterion {index + 1} name
          </label>
          <input
            id={`${fieldPrefix}-name`}
            type="text"
            placeholder={`Criterion ${index + 1} name`}
            disabled={isSubmitting}
            aria-invalid={!!criterionErrors?.name}
            aria-describedby={
              criterionErrors?.name
                ? `${fieldPrefix}-name-error`
                : undefined
            }
            className="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            {...register(`${fieldPrefix}.name`)}
          />
          {criterionErrors?.name && (
            <p
              id={`${fieldPrefix}-name-error`}
              className="mt-0.5 text-xs text-red-600"
              role="alert"
            >
              {criterionErrors.name.message}
            </p>
          )}
        </div>

        {/* Weight field */}
        <div className="w-20 shrink-0">
          <label htmlFor={`${fieldPrefix}-weight`} className="sr-only">
            Criterion {index + 1} weight (%)
          </label>
          <div className="relative">
            <input
              id={`${fieldPrefix}-weight`}
              type="number"
              min={0.01}
              max={100}
              step={0.01}
              placeholder="0.01"
              disabled={isSubmitting}
              aria-invalid={!!criterionErrors?.weight}
              aria-describedby={
                criterionErrors?.weight
                  ? `${fieldPrefix}-weight-error`
                  : undefined
              }
              className="block w-full rounded-md border border-gray-300 px-3 py-1.5 pr-6 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register(`${fieldPrefix}.weight`, { valueAsNumber: true })}
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">
              %
            </span>
          </div>
          {criterionErrors?.weight && (
            <p
              id={`${fieldPrefix}-weight-error`}
              className="mt-0.5 text-xs text-red-600"
              role="alert"
            >
              {criterionErrors.weight.message}
            </p>
          )}
        </div>

        {/* Expand/collapse details */}
        <button
          type="button"
          onClick={onToggleExpand}
          aria-label={
            isExpanded
              ? `Collapse criterion ${index + 1} details`
              : `Expand criterion ${index + 1} details`
          }
          aria-expanded={isExpanded}
          className="shrink-0 rounded p-1 text-gray-400 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {isExpanded ? "▾" : "▸"}
        </button>

        {/* Remove button */}
        <button
          type="button"
          onClick={onRemove}
          disabled={total <= 1 || isSubmitting}
          aria-label={`Remove criterion ${index + 1}`}
          className="shrink-0 rounded p-1 text-gray-400 hover:text-red-600 disabled:opacity-30 focus:outline-none focus:ring-2 focus:ring-red-500"
        >
          ✕
        </button>
      </div>

      {/* Expanded detail panel */}
      {isExpanded && (
        <div className="border-t border-gray-100 px-4 pb-4 pt-3 space-y-3">
          {/* Description */}
          <div>
            <label
              htmlFor={`${fieldPrefix}-description`}
              className="block text-xs font-medium text-gray-600"
            >
              Description{" "}
              <span className="font-normal text-gray-400">(optional)</span>
            </label>
            <textarea
              id={`${fieldPrefix}-description`}
              rows={2}
              placeholder="What this criterion assesses…"
              disabled={isSubmitting}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 resize-none"
              {...register(`${fieldPrefix}.description`)}
            />
            {criterionErrors?.description && (
              <p className="mt-0.5 text-xs text-red-600" role="alert">
                {criterionErrors.description.message}
              </p>
            )}
          </div>

          {/* Min / Max score */}
          <div className="flex gap-4">
            <div className="flex-1">
              <label
                htmlFor={`${fieldPrefix}-min_score`}
                className="block text-xs font-medium text-gray-600"
              >
                Min score
              </label>
              <input
                id={`${fieldPrefix}-min_score`}
                type="number"
                min={1}
                step={1}
                disabled={isSubmitting}
                aria-invalid={!!criterionErrors?.min_score}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                {...register(`${fieldPrefix}.min_score`, {
                  valueAsNumber: true,
                })}
              />
              {criterionErrors?.min_score && (
                <p className="mt-0.5 text-xs text-red-600" role="alert">
                  {criterionErrors.min_score.message}
                </p>
              )}
            </div>
            <div className="flex-1">
              <label
                htmlFor={`${fieldPrefix}-max_score`}
                className="block text-xs font-medium text-gray-600"
              >
                Max score
              </label>
              <input
                id={`${fieldPrefix}-max_score`}
                type="number"
                min={1}
                step={1}
                disabled={isSubmitting}
                aria-invalid={!!criterionErrors?.max_score}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                {...register(`${fieldPrefix}.max_score`, {
                  valueAsNumber: true,
                })}
              />
              {criterionErrors?.max_score && (
                <p className="mt-0.5 text-xs text-red-600" role="alert">
                  {criterionErrors.max_score.message}
                </p>
              )}
            </div>
          </div>

          {/* Anchor descriptions */}
          {scoreRange.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600">
                Anchor descriptions{" "}
                <span className="font-normal text-gray-400">
                  (optional — score-level exemplars)
                </span>
              </p>
              <div className="mt-2 space-y-2">
                {scoreRange.map((score) => (
                  <div key={score} className="flex items-start gap-2">
                    <span className="mt-1.5 w-6 shrink-0 text-center text-xs font-semibold text-gray-500">
                      {score}
                    </span>
                    <Controller
                      control={control}
                      name={`${fieldPrefix}.anchor_descriptions`}
                      render={({ field }) => {
                        const currentMap =
                          (field.value as AnchorDescriptions | undefined) ??
                          {};
                        return (
                          <input
                            type="text"
                            placeholder={`What a "${score}" looks like…`}
                            disabled={isSubmitting}
                            value={currentMap[String(score)] ?? ""}
                            onChange={(e) => {
                              const updated = {
                                ...currentMap,
                                [String(score)]: e.target.value,
                              };
                              field.onChange(updated);
                            }}
                            aria-label={`Anchor description for score ${score} of criterion ${index + 1}`}
                            className="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                          />
                        );
                      }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export interface RubricBuilderFormProps {
  /** Populated when editing an existing rubric. */
  defaultValues?: Partial<RubricFormValues>;
  /** Called with the validated form values on successful submit. */
  onSave: (values: RubricFormValues) => Promise<void>;
  /** Called when the user clicks Cancel or navigates away without saving. */
  onCancel: () => void;
  /** Label shown on the primary submit button. */
  saveLabel?: string;
}

export function RubricBuilderForm({
  defaultValues,
  onSave,
  onCancel,
  saveLabel = "Save rubric",
}: RubricBuilderFormProps) {
  // Normalize provided criteria so every entry has all required fields.
  // Without this, criteria items that omit optional fields (e.g. description,
  // anchor_descriptions) cause Zod to fail on submit even though the prop type
  // allows partial entries.
  const normalizedDefaults: RubricFormValues = {
    name: defaultValues?.name ?? "",
    criteria:
      defaultValues?.criteria && defaultValues.criteria.length > 0
        ? defaultValues.criteria.map((c, i) => ({
            ...createEmptyCriterion(i + 1),
            ...c,
          }))
        : Array.from({ length: DEFAULT_CRITERION_COUNT }, (_, i) =>
            createEmptyCriterion(i + 1),
          ),
  };

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<RubricFormValues>({
    resolver: zodResolver(rubricFormSchema),
    defaultValues: normalizedDefaults,
  });

  const { fields, append, remove, move } = useFieldArray({
    control,
    name: "criteria",
  });

  // Live weight sum
  const liveCriteria = useWatch({ control, name: "criteria" });
  const weightSum = computeWeightSum(liveCriteria ?? []);

  // Track which criterion rows are expanded — keyed by stable field.id so
  // reordering does not collapse/expand the wrong row.
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const toggleExpand = useCallback((id: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // Reset expanded set when rows are added/removed so stale indices are cleared
  useEffect(() => {
    setExpandedRows(new Set());
  }, [fields.length]);

  // Unsaved-changes guard — warn on browser navigation
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        // Legacy support
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  // Server-level error message
  const [serverError, setServerError] = useState<string | null>(null);

  // Track whether the user has attempted to submit (to show weight-sum error)
  const [hasAttemptedSubmit, setHasAttemptedSubmit] = useState(false);

  // Template picker visibility
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);

  const handleApplyTemplate = (values: TemplateApplyValues) => {
    reset({
      name: values.name,
      criteria:
        values.criteria.length > 0 ? values.criteria : normalizedDefaults.criteria,
    });
    setHasAttemptedSubmit(false);
  };

  const onSubmit = async (values: RubricFormValues) => {
    setServerError(null);
    try {
      await onSave(values);
    } catch (err) {
      if (process.env.NODE_ENV !== "production") {
        // Development-only: avoid leaking raw error details in production.
        console.error("[RubricBuilderForm] save failed:", err);
      }
      setServerError("Failed to save rubric. Please try again.");
    }
  };

  const handleFormError = () => {
    setHasAttemptedSubmit(true);
  };

  // ---------------------------------------------------------------------------
  // Drag-and-drop state
  // ---------------------------------------------------------------------------

  const dragIndexRef = useRef<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  const handleDragStart = useCallback(
    (idx: number) => (e: React.DragEvent<HTMLDivElement>) => {
      dragIndexRef.current = idx;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(idx));
    },
    [],
  );

  const handleDragOver = useCallback(
    (idx: number) => (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDragOverIndex(idx);
    },
    [],
  );

  const handleDrop = useCallback(
    (idx: number) => (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const from = dragIndexRef.current;
      if (from !== null && from !== idx) {
        move(from, idx);
      }
      dragIndexRef.current = null;
      setDragOverIndex(null);
    },
    [move],
  );

  const handleDragEnd = useCallback(() => {
    dragIndexRef.current = null;
    setDragOverIndex(null);
  }, []);

  // ---------------------------------------------------------------------------
  // Cancel guard
  // ---------------------------------------------------------------------------

  const handleCancel = () => {
    if (
      isDirty &&
      !window.confirm(
        "You have unsaved changes. Are you sure you want to cancel?",
      )
    ) {
      return;
    }
    reset();
    onCancel();
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const canAddMore = fields.length < 8;

  // Weight-sum refinement error (path: ["criteria"])
  // Note: shown via hasAttemptedSubmit state, not via form error state,
  // because React Hook Form stores fieldArray-level refinement errors in a
  // structure that differs across resolver versions.

  return (
    <form
      onSubmit={handleSubmit(onSubmit, handleFormError)}
      noValidate
      className="space-y-5"
      aria-label="Rubric builder"
    >
      {/* Template picker dialog (rendered outside form flow) */}
      {showTemplatePicker && (
        <TemplatePicker
          onApply={handleApplyTemplate}
          onClose={() => setShowTemplatePicker(false)}
        />
      )}

      {/* Rubric name + load-from-template row */}
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <label
            htmlFor="rubric-name"
            className="block text-sm font-medium text-gray-700"
          >
            Rubric name
          </label>
          <input
            id="rubric-name"
            type="text"
            placeholder="e.g. 5-Paragraph Essay"
            disabled={isSubmitting}
            aria-invalid={!!errors.name}
            aria-describedby={errors.name ? "rubric-name-error" : undefined}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            {...register("name")}
          />
          {errors.name && (
            <p
              id="rubric-name-error"
              className="mt-1 text-sm text-red-600"
              role="alert"
            >
              {errors.name.message}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setShowTemplatePicker(true)}
          disabled={isSubmitting}
          className="shrink-0 rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
        >
          Load from template
        </button>
      </div>

      {/* Criteria section */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-medium text-gray-700">
            Criteria{" "}
            <span className="text-xs font-normal text-gray-400">
              (1-8, drag to reorder)
            </span>
          </p>
          <WeightSumIndicator sum={weightSum} />
        </div>

        {/* Criteria list */}
        <div className="space-y-2" role="list" aria-label="Rubric criteria">
          {fields.map((field, idx) => (
            <div key={field.id} role="listitem">
              <CriterionRow
                index={idx}
                total={fields.length}
                isSubmitting={isSubmitting}
                isExpanded={expandedRows.has(field.id)}
                onToggleExpand={() => toggleExpand(field.id)}
                onMoveUp={() => move(idx, idx - 1)}
                onMoveDown={() => move(idx, idx + 1)}
                onRemove={() => remove(idx)}
                fieldPrefix={`criteria.${idx}`}
                register={register}
                control={control}
                errors={errors.criteria}
                onDragStart={handleDragStart(idx)}
                onDragOver={handleDragOver(idx)}
                onDrop={handleDrop(idx)}
                onDragEnd={handleDragEnd}
                isDragOver={dragOverIndex === idx}
              />
            </div>
          ))}
        </div>

        {/* Criteria-level error (weight sum) — shown after first submit attempt */}
        {hasAttemptedSubmit &&
          Math.round(weightSum * 100) / 100 !== 100 && (
            <p className="mt-2 text-sm text-red-600" role="alert">
              Criterion weights must sum to 100%. Current total:{" "}
              {(Math.round(weightSum * 100) / 100).toFixed(2).replace(/\.?0+$/, "")}%.
            </p>
          )}

        {/* Add criterion button */}
        {canAddMore && (
          <button
            type="button"
            onClick={() => append(createEmptyCriterion(fields.length + 1))}
            disabled={isSubmitting}
            className="mt-3 flex items-center gap-1 rounded-md border border-dashed border-gray-300 px-4 py-2 text-sm text-gray-600 hover:border-blue-400 hover:text-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 w-full justify-center"
          >
            + Add criterion
          </button>
        )}
      </div>

      {/* Server-side error */}
      {serverError && (
        <p
          className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
        >
          {serverError}
        </p>
      )}

      {/* Form actions */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={handleCancel}
          disabled={isSubmitting}
          className="flex-1 rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="flex-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
        >
          {isSubmitting ? "Saving…" : saveLabel}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Helpers to convert API response ↔ form values
// ---------------------------------------------------------------------------

/**
 * Convert the API's criterion response array (ordered by display_order)
 * into the form's criteria array.
 *
 * @deprecated Import `convertApiCriteriaToForm` from `rubricFormUtils` directly.
 *   This re-export exists for backward compatibility.
 */
export function apiCriteriaToFormCriteria(
  apiCriteria: Array<{
    name: string;
    description?: string | null;
    weight: number;
    min_score: number;
    max_score: number;
    anchor_descriptions?: AnchorDescriptions | null;
  }>,
): RubricFormValues["criteria"] {
  return convertApiCriteriaToForm(apiCriteria);
}
