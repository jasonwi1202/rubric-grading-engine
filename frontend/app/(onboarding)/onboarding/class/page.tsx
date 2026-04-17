"use client";

import { useState } from "react";
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
  name: z.string().min(1, "Class name is required").max(200, "Class name is too long"),
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

const CURRENT_YEAR = new Date().getFullYear();
const ACADEMIC_YEARS = [
  `${CURRENT_YEAR - 1}–${CURRENT_YEAR}`,
  `${CURRENT_YEAR}–${CURRENT_YEAR + 1}`,
  `${CURRENT_YEAR + 1}–${CURRENT_YEAR + 2}`,
];

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

/**
 * Onboarding Step 1 — Create your first class.
 *
 * Teachers can create a class by filling in the name and grade level, or
 * skip to Step 2. Either path continues to /onboarding/rubric.
 *
 * Security: no student PII is collected here.
 */
export default function OnboardingClassPage() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ClassFormValues>({
    resolver: zodResolver(classSchema),
    defaultValues: {
      academic_year: ACADEMIC_YEARS[1],
    },
  });

  const onSubmit = async (values: ClassFormValues) => {
    setServerError(null);
    try {
      await createClass({
        name: values.name,
        grade_level: values.grade_level,
        academic_year: values.academic_year ?? undefined,
      });
      router.push("/onboarding/rubric");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/login?next=/onboarding/class");
      } else {
        setServerError("Failed to create class. Please try again.");
      }
    }
  };

  const handleSkip = () => {
    router.push("/onboarding/rubric");
  };

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      {/* Progress indicator */}
      <p className="mb-6 text-sm font-medium text-gray-500" aria-label="Step 1 of 2">
        Step 1 of 2
      </p>

      <div className="w-full max-w-md rounded-lg bg-white p-8 shadow-md">
        <h1 className="mb-2 text-2xl font-bold text-gray-900">
          Create your first class
        </h1>
        <p className="mb-6 text-sm text-gray-600">
          Set up a class to organize your students and assignments.
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
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              aria-describedby={errors.name ? "name-error" : undefined}
              aria-invalid={!!errors.name}
              disabled={isSubmitting}
              {...register("name")}
            />
            {errors.name && (
              <p id="name-error" className="mt-1 text-sm text-red-600" role="alert">
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
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              aria-describedby={errors.grade_level ? "grade-level-error" : undefined}
              aria-invalid={!!errors.grade_level}
              disabled={isSubmitting}
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
                className="mt-1 text-sm text-red-600"
                role="alert"
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
              className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              disabled={isSubmitting}
              {...register("academic_year")}
            >
              {ACADEMIC_YEARS.map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
          </div>

          {/* Server-side error */}
          {serverError && (
            <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
              {serverError}
            </p>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          >
            {isSubmitting ? "Creating class…" : "Create class & continue"}
          </button>
        </form>

        {/* Skip link */}
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={handleSkip}
            disabled={isSubmitting}
            className="text-sm text-gray-500 hover:text-gray-700 underline focus:outline-none focus:ring-2 focus:ring-blue-500 rounded disabled:opacity-50"
          >
            I&apos;ll set up my class later
          </button>
        </div>
      </div>
    </div>
  );
}
