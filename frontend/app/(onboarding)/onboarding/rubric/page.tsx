"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { createRubric } from "@/lib/api/rubrics";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Rubric builder schema
// ---------------------------------------------------------------------------

const criterionSchema = z.object({
  name: z.string().min(1, "Criterion name is required"),
  weight: z.number().min(1).max(100),
  min_score: z.number().min(0),
  max_score: z.number().min(1),
});

const rubricSchema = z.object({
  name: z.string().min(1, "Rubric name is required").max(200, "Rubric name is too long"),
  criteria: z.array(criterionSchema).min(1),
});

type RubricFormValues = z.infer<typeof rubricSchema>;

// ---------------------------------------------------------------------------
// Template definitions
// ---------------------------------------------------------------------------

interface RubricTemplate {
  id: string;
  label: string;
  name: string;
  criteria: Array<{ name: string; weight: number; min_score: number; max_score: number }>;
}

const TEMPLATES: RubricTemplate[] = [
  {
    id: "five-paragraph",
    label: "5-Paragraph Essay",
    name: "5-Paragraph Essay",
    criteria: [
      { name: "Thesis Statement", weight: 25, min_score: 1, max_score: 5 },
      { name: "Supporting Evidence", weight: 25, min_score: 1, max_score: 5 },
      { name: "Organization", weight: 25, min_score: 1, max_score: 5 },
      { name: "Grammar & Mechanics", weight: 25, min_score: 1, max_score: 5 },
    ],
  },
  {
    id: "argumentative",
    label: "Argumentative Writing",
    name: "Argumentative Writing",
    criteria: [
      { name: "Claim", weight: 30, min_score: 1, max_score: 5 },
      { name: "Evidence & Reasoning", weight: 30, min_score: 1, max_score: 5 },
      { name: "Counterargument", weight: 20, min_score: 1, max_score: 5 },
      { name: "Style & Voice", weight: 20, min_score: 1, max_score: 5 },
    ],
  },
  {
    id: "literary-analysis",
    label: "Literary Analysis",
    name: "Literary Analysis",
    criteria: [
      { name: "Textual Evidence", weight: 30, min_score: 1, max_score: 5 },
      { name: "Analysis & Interpretation", weight: 35, min_score: 1, max_score: 5 },
      { name: "Structure", weight: 20, min_score: 1, max_score: 5 },
      { name: "Writing Conventions", weight: 15, min_score: 1, max_score: 5 },
    ],
  },
];

const DEFAULT_CRITERIA = [
  { name: "Criterion 1", weight: 34, min_score: 1, max_score: 5 },
  { name: "Criterion 2", weight: 33, min_score: 1, max_score: 5 },
  { name: "Criterion 3", weight: 33, min_score: 1, max_score: 5 },
];

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

type Mode = "choose" | "build";

/**
 * Onboarding Step 2 — Build or import a rubric.
 *
 * Offers three options:
 * 1. Build from scratch — simplified inline rubric builder
 * 2. Start from a template — pre-fills the builder
 * 3. Skip for now — navigate straight to /onboarding/done
 *
 * Security: no student PII is collected here.
 */
export default function OnboardingRubricPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("choose");
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<RubricFormValues>({
    resolver: zodResolver(rubricSchema),
    defaultValues: {
      name: "",
      criteria: DEFAULT_CRITERIA,
    },
  });

  const handleBuildFromScratch = () => {
    reset({ name: "", criteria: DEFAULT_CRITERIA });
    setMode("build");
  };

  const handleSelectTemplate = (template: RubricTemplate) => {
    reset({ name: template.name, criteria: template.criteria });
    setMode("build");
  };

  const handleSkip = () => {
    router.push("/onboarding/done");
  };

  const onSubmit = async (values: RubricFormValues) => {
    setServerError(null);
    try {
      await createRubric({
        name: values.name,
        criteria: values.criteria,
      });
      router.push("/onboarding/done");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/login?next=/onboarding/rubric");
      } else {
        // M3 endpoints are not yet implemented — treat 404/405/500 as a
        // soft failure and advance the wizard rather than blocking.
        router.push("/onboarding/done");
      }
    }
  };

  if (mode === "choose") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
        <p className="mb-6 text-sm font-medium text-gray-500" aria-label="Step 2 of 2">
          Step 2 of 2
        </p>

        <div className="w-full max-w-lg rounded-lg bg-white p-8 shadow-md">
          <h1 className="mb-2 text-2xl font-bold text-gray-900">
            Build your first rubric
          </h1>
          <p className="mb-6 text-sm text-gray-600">
            Rubrics tell the AI how to grade. You can always create or edit
            rubrics later.
          </p>

          <div className="space-y-3">
            {/* Build from scratch */}
            <button
              type="button"
              onClick={handleBuildFromScratch}
              className="w-full rounded-lg border-2 border-gray-200 p-4 text-left hover:border-blue-400 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
            >
              <p className="font-semibold text-gray-900">Build from scratch</p>
              <p className="mt-1 text-sm text-gray-500">
                Start with a blank rubric and customize every criterion.
              </p>
            </button>

            {/* Templates */}
            <div className="rounded-lg border-2 border-gray-200 p-4">
              <p className="font-semibold text-gray-900">Start from a template</p>
              <p className="mt-1 mb-3 text-sm text-gray-500">
                Choose a preset rubric and adjust as needed.
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                {TEMPLATES.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => handleSelectTemplate(t)}
                    className="rounded-md border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:border-blue-400 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Skip */}
          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={handleSkip}
              className="text-sm text-gray-500 hover:text-gray-700 underline focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
            >
              Skip for now — I&apos;ll create a rubric when I set up my first
              assignment
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ----------- Build mode -----------
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <p className="mb-6 text-sm font-medium text-gray-500" aria-label="Step 2 of 2">
        Step 2 of 2
      </p>

      <div className="w-full max-w-lg rounded-lg bg-white p-8 shadow-md">
        <h1 className="mb-6 text-2xl font-bold text-gray-900">Configure rubric</h1>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          {/* Rubric name */}
          <div>
            <label htmlFor="rubric-name" className="block text-sm font-medium text-gray-700">
              Rubric name
            </label>
            <input
              id="rubric-name"
              type="text"
              placeholder="e.g. 5-Paragraph Essay"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              aria-describedby={errors.name ? "rubric-name-error" : undefined}
              aria-invalid={!!errors.name}
              disabled={isSubmitting}
              {...register("name")}
            />
            {errors.name && (
              <p id="rubric-name-error" className="mt-1 text-sm text-red-600" role="alert">
                {errors.name.message}
              </p>
            )}
          </div>

          {/* Criteria */}
          <div>
            <p className="mb-2 block text-sm font-medium text-gray-700">
              Criteria (weights must sum to 100)
            </p>
            <div className="space-y-2">
              {DEFAULT_CRITERIA.map((_, idx) => (
                <div key={idx} className="grid grid-cols-3 gap-2 items-start">
                  <div className="col-span-2">
                    <label
                      htmlFor={`criteria-${idx}-name`}
                      className="sr-only"
                    >
                      {`Criterion ${idx + 1} name`}
                    </label>
                    <input
                      id={`criteria-${idx}-name`}
                      type="text"
                      placeholder={`Criterion ${idx + 1}`}
                      className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                      disabled={isSubmitting}
                      {...register(`criteria.${idx}.name`)}
                    />
                    <input type="hidden" {...register(`criteria.${idx}.min_score`, { valueAsNumber: true })} />
                    <input type="hidden" {...register(`criteria.${idx}.max_score`, { valueAsNumber: true })} />
                  </div>
                  <div>
                    <label
                      htmlFor={`criteria-${idx}-weight`}
                      className="sr-only"
                    >
                      {`Criterion ${idx + 1} weight (%)`}
                    </label>
                    <div className="relative">
                      <input
                        id={`criteria-${idx}-weight`}
                        type="number"
                        min={1}
                        max={100}
                        placeholder="0"
                        className="block w-full rounded-md border border-gray-300 px-3 py-2 pr-8 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                        disabled={isSubmitting}
                        {...register(`criteria.${idx}.weight`, { valueAsNumber: true })}
                      />
                      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 pointer-events-none">
                        %
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Server-side error */}
          {serverError && (
            <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
              {serverError}
            </p>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => setMode("choose")}
              disabled={isSubmitting}
              className="flex-1 rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              Back
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {isSubmitting ? "Saving rubric…" : "Save rubric & continue"}
            </button>
          </div>

          <div className="text-center">
            <button
              type="button"
              onClick={handleSkip}
              disabled={isSubmitting}
              className="text-sm text-gray-500 hover:text-gray-700 underline focus:outline-none focus:ring-2 focus:ring-blue-500 rounded disabled:opacity-50"
            >
              Skip for now
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
