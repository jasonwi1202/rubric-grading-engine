"use client";

/**
 * /dashboard/classes/[classId]/assignments/new
 *
 * Assignment creation form.
 *
 * Fields:
 * - Title (required, max 255)
 * - Writing prompt (optional, max 5000)
 * - Rubric picker — lists all teacher rubrics; selecting one previews criteria
 * - Due date (optional)
 *
 * All server state via React Query. No useEffect+fetch.
 * Security: no student PII is handled here.
 */

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listRubrics, getRubric } from "@/lib/api/rubrics";
import { createAssignment } from "@/lib/api/assignments";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Form schema
// ---------------------------------------------------------------------------

const assignmentSchema = z.object({
  title: z
    .string()
    .min(1, "Title is required")
    .max(255, "Title is too long"),
  prompt: z.string().max(5000, "Prompt is too long"),
  rubric_id: z.string().min(1, "Please select a rubric"),
  due_date: z.string(),
});

type AssignmentFormValues = z.infer<typeof assignmentSchema>;

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function NewAssignmentPage() {
  const { classId } = useParams<{ classId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<AssignmentFormValues>({
    resolver: zodResolver(assignmentSchema),
    defaultValues: {
      title: "",
      prompt: "",
      rubric_id: "",
      due_date: "",
    },
  });

  const selectedRubricId = watch("rubric_id");

  // Fetch teacher's rubric list
  const {
    data: rubrics,
    isLoading: rubricsLoading,
    isError: rubricsError,
  } = useQuery({
    queryKey: ["rubrics"],
    queryFn: listRubrics,
  });

  // Fetch selected rubric's full criteria for preview
  const {
    data: selectedRubric,
    isLoading: rubricDetailLoading,
  } = useQuery({
    queryKey: ["rubric", selectedRubricId],
    queryFn: () => getRubric(selectedRubricId),
    enabled: !!selectedRubricId,
  });

  const createMutation = useMutation({
    mutationFn: (values: AssignmentFormValues) =>
      createAssignment(classId, {
        title: values.title,
        prompt: values.prompt || null,
        rubric_id: values.rubric_id,
        due_date: values.due_date || null,
      }),
    onSuccess: (assignment) => {
      queryClient.invalidateQueries({ queryKey: ["assignments", classId] });
      router.push(`/dashboard/assignments/${assignment.id}`);
    },
    onError: (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(
          `/login?next=/dashboard/classes/${classId}/assignments/new`,
        );
        return;
      }
      setServerError("Failed to create assignment. Please try again.");
    },
  });

  const onSubmit = (values: AssignmentFormValues) => {
    setServerError(null);
    createMutation.mutate(values);
  };

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="mb-6 text-sm text-gray-500">
        <Link href="/dashboard/classes" className="hover:text-gray-700 underline">
          Classes
        </Link>
        <span aria-hidden="true" className="mx-2">/</span>
        <Link
          href={`/dashboard/classes/${classId}`}
          className="hover:text-gray-700 underline"
        >
          Class
        </Link>
        <span aria-hidden="true" className="mx-2">/</span>
        <span className="text-gray-900">New assignment</span>
      </nav>

      <div className="rounded-lg bg-white p-8 shadow-md">
        <h1 className="mb-2 text-2xl font-bold text-gray-900">
          Create assignment
        </h1>
        <p className="mb-6 text-sm text-gray-600">
          Set up a new writing assignment for this class.
        </p>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-5">
          {/* Title */}
          <div>
            <label
              htmlFor="title"
              className="block text-sm font-medium text-gray-700"
            >
              Title <span aria-hidden="true" className="text-red-500">*</span>
            </label>
            <input
              id="title"
              type="text"
              autoComplete="off"
              placeholder="e.g. Persuasive Essay — Unit 3"
              disabled={isSubmitting}
              aria-describedby={errors.title ? "title-error" : undefined}
              aria-invalid={!!errors.title}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register("title")}
            />
            {errors.title && (
              <p id="title-error" role="alert" className="mt-1 text-sm text-red-600">
                {errors.title.message}
              </p>
            )}
          </div>

          {/* Writing prompt */}
          <div>
            <label
              htmlFor="prompt"
              className="block text-sm font-medium text-gray-700"
            >
              Writing prompt{" "}
              <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <textarea
              id="prompt"
              rows={4}
              disabled={isSubmitting}
              placeholder="Describe the writing task or instructions for students…"
              aria-describedby={errors.prompt ? "prompt-error" : undefined}
              aria-invalid={!!errors.prompt}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register("prompt")}
            />
            {errors.prompt && (
              <p id="prompt-error" role="alert" className="mt-1 text-sm text-red-600">
                {errors.prompt.message}
              </p>
            )}
          </div>

          {/* Rubric picker */}
          <div>
            <label
              htmlFor="rubric_id"
              className="block text-sm font-medium text-gray-700"
            >
              Rubric <span aria-hidden="true" className="text-red-500">*</span>
            </label>

            {rubricsError && (
              <p
                role="alert"
                className="mt-1 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
              >
                Failed to load rubrics. Please refresh the page.
              </p>
            )}

            {!rubricsError && (
              <select
                id="rubric_id"
                disabled={isSubmitting || rubricsLoading}
                aria-describedby={errors.rubric_id ? "rubric-id-error" : undefined}
                aria-invalid={!!errors.rubric_id}
                aria-busy={rubricsLoading}
                className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                {...register("rubric_id")}
              >
                <option value="" disabled>
                  {rubricsLoading ? "Loading rubrics…" : "Select a rubric"}
                </option>
                {rubrics?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                    {r.criterion_count > 0
                      ? ` (${r.criterion_count} ${r.criterion_count === 1 ? "criterion" : "criteria"})`
                      : ""}
                  </option>
                ))}
              </select>
            )}

            {errors.rubric_id && (
              <p id="rubric-id-error" role="alert" className="mt-1 text-sm text-red-600">
                {errors.rubric_id.message}
              </p>
            )}

            {/* No rubrics — prompt to create one */}
            {!rubricsLoading && !rubricsError && rubrics?.length === 0 && (
              <p className="mt-2 text-sm text-gray-500">
                You have no rubrics yet.{" "}
                <Link
                  href="/dashboard/rubrics/new"
                  className="font-medium text-blue-600 underline hover:text-blue-800"
                >
                  Create your first rubric
                </Link>
              </p>
            )}

            {/* Rubric criteria preview */}
            {selectedRubricId && (
              <div
                aria-live="polite"
                className="mt-3 rounded-md border border-gray-200 bg-gray-50 p-4"
              >
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                  Criteria preview
                </p>
                {rubricDetailLoading && (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <div
                        key={i}
                        className="h-4 animate-pulse rounded bg-gray-200"
                      />
                    ))}
                  </div>
                )}
                {!rubricDetailLoading && selectedRubric && (
                  <ul className="space-y-1.5" role="list">
                    {selectedRubric.criteria.map((c) => (
                      <li
                        key={c.id}
                        className="flex items-center justify-between text-sm text-gray-700"
                      >
                        <span className="font-medium">{c.name}</span>
                        <span className="text-gray-500">
                          {c.weight}% · {c.min_score}–{c.max_score} pts
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>

          {/* Due date */}
          <div>
            <label
              htmlFor="due_date"
              className="block text-sm font-medium text-gray-700"
            >
              Due date{" "}
              <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <input
              id="due_date"
              type="date"
              disabled={isSubmitting}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register("due_date")}
            />
          </div>

          {/* Server error */}
          {serverError && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
            >
              {serverError}
            </p>
          )}

          {/* Actions */}
          <div className="flex items-center justify-between pt-2">
            <Link
              href={`/dashboard/classes/${classId}`}
              className="text-sm text-gray-500 hover:text-gray-700 underline"
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={isSubmitting || createMutation.isPending}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {isSubmitting || createMutation.isPending
                ? "Creating…"
                : "Create assignment"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
