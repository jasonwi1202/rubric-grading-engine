"use client";

/**
 * /dashboard/classes — list all classes for the authenticated teacher.
 *
 * All server state via React Query. No useEffect+fetch.
 * Security: no student PII displayed here — class names and grade levels only.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { listClasses } from "@/lib/api/classes";

export default function ClassesPage() {
  const { data: classes, isLoading, isError } = useQuery({
    queryKey: ["classes", { is_archived: false }],
    queryFn: () => listClasses({ is_archived: false }),
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Page header */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Classes</h1>
        <Link
          href="/dashboard/classes/new"
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          New class
        </Link>
      </div>

      {/* Loading */}
      {isLoading && (
        <div aria-live="polite" aria-busy="true" className="py-12 text-center text-sm text-gray-500">
          Loading classes…
        </div>
      )}

      {/* Error */}
      {isError && (
        <p role="alert" className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load classes. Please refresh the page.
        </p>
      )}

      {/* Empty state */}
      {!isLoading && !isError && classes?.length === 0 && (
        <div className="rounded-md border border-dashed border-gray-300 py-16 text-center">
          <p className="mb-3 text-sm text-gray-600">
            You have no active classes yet.
          </p>
          <Link
            href="/dashboard/classes/new"
            className="text-sm font-medium text-blue-600 underline hover:text-blue-800"
          >
            Create your first class
          </Link>
        </div>
      )}

      {/* Class cards */}
      {!isLoading && !isError && classes && classes.length > 0 && (
        <ul className="space-y-3" role="list">
          {classes.map((cls) => (
            <li key={cls.id}>
              <Link
                href={`/dashboard/classes/${cls.id}`}
                className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-5 py-4 shadow-sm hover:border-blue-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow"
              >
                <div>
                  <p className="font-semibold text-gray-900">{cls.name}</p>
                  <p className="mt-0.5 text-sm text-gray-500">
                    {cls.grade_level}
                    {cls.academic_year ? ` · ${cls.academic_year}` : ""}
                  </p>
                </div>
                {cls.student_count !== undefined && (
                  <span className="text-sm text-gray-500">
                    {cls.student_count}{" "}
                    {cls.student_count === 1 ? "student" : "students"}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
