"use client";

/**
 * /dashboard/classes/new — create a new class.
 *
 * Reuses the same form schema and grade level / academic year constants as
 * the onboarding wizard, but navigates back to the class list on success
 * rather than continuing through the onboarding flow.
 *
 * Security: no student PII is collected here.
 */

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { createClass } from "@/lib/api/classes";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Form schema
// ---------------------------------------------------------------------------

const classSchema = z.object({
  name: z
    .string()
    .min(1, "Class name is required")
    .max(200, "Class name is too long"),
  grade_level: z.string().min(1, "Grade level is required"),
  academic_year: z.string().optional(),
});

type ClassFormValues = z.infer<typeof classSchema>;

const GRADE_LEVELS = [
  "Kindergarten",
  "Grade 1",
  "Grade 2",
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
  "College / University",
  "Other",
];

// Computed once at module load time, not on every render.
const CURRENT_YEAR = new Date().getFullYear();
const ACADEMIC_YEARS = [
  `${CURRENT_YEAR - 1}–${CURRENT_YEAR}`,
  `${CURRENT_YEAR}–${CURRENT_YEAR + 1}`,
  `${CURRENT_YEAR + 1}–${CURRENT_YEAR + 2}`,
];

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function NewClassPage() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ClassFormValues>({
    resolver: zodResolver(classSchema),
    defaultValues: { academic_year: ACADEMIC_YEARS[1] },
  });

  const onSubmit = async (values: ClassFormValues) => {
    setServerError(null);
    try {
      const cls = await createClass({
        name: values.name,
        grade_level: values.grade_level,
        academic_year: values.academic_year ?? undefined,
      });
      router.push(`/dashboard/classes/${cls.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/login?next=/dashboard/classes/new");
        return;
      }
      setServerError("Failed to create class. Please try again.");
    }
  };

  return (
    <div className="mx-auto max-w-lg px-4 py-8">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="mb-6 text-sm text-gray-500">
        <Link href="/dashboard/classes" className="hover:text-gray-700 underline">
          Classes
        </Link>
        <span aria-hidden="true" className="mx-2">
          /
        </span>
        <span className="text-gray-900">New class</span>
      </nav>

      <div className="rounded-lg bg-white p-8 shadow-md">
        <h1 className="mb-2 text-2xl font-bold text-gray-900">
          Create a class
        </h1>
        <p className="mb-6 text-sm text-gray-600">
          Organize your students and assignments by class.
        </p>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          {/* Class name */}
          <div>
            <label
              htmlFor="name"
              className="block text-sm font-medium text-gray-700"
            >
              Class name
            </label>
            <input
              id="name"
              type="text"
              autoComplete="off"
              placeholder="e.g. Period 3 English"
              disabled={isSubmitting}
              aria-describedby={errors.name ? "name-error" : undefined}
              aria-invalid={!!errors.name}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register("name")}
            />
            {errors.name && (
              <p id="name-error" role="alert" className="mt-1 text-sm text-red-600">
                {errors.name.message}
              </p>
            )}
          </div>

          {/* Grade level */}
          <div>
            <label
              htmlFor="grade_level"
              className="block text-sm font-medium text-gray-700"
            >
              Grade level
            </label>
            <select
              id="grade_level"
              disabled={isSubmitting}
              aria-describedby={errors.grade_level ? "grade-level-error" : undefined}
              aria-invalid={!!errors.grade_level}
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register("grade_level")}
              defaultValue=""
            >
              <option value="" disabled>
                Select a grade level
              </option>
              {GRADE_LEVELS.map((grade) => (
                <option key={grade} value={grade}>
                  {grade}
                </option>
              ))}
            </select>
            {errors.grade_level && (
              <p
                id="grade-level-error"
                role="alert"
                className="mt-1 text-sm text-red-600"
              >
                {errors.grade_level.message}
              </p>
            )}
          </div>

          {/* Academic year */}
          <div>
            <label
              htmlFor="academic_year"
              className="block text-sm font-medium text-gray-700"
            >
              Academic year
            </label>
            <select
              id="academic_year"
              disabled={isSubmitting}
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register("academic_year")}
            >
              {ACADEMIC_YEARS.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
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
              href="/dashboard/classes"
              className="text-sm text-gray-500 hover:text-gray-700 underline"
            >
              Cancel
            </Link>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {isSubmitting ? "Creating…" : "Create class"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
