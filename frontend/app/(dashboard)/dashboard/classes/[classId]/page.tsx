"use client";

/**
 * /dashboard/classes/[classId] — class detail and roster management.
 *
 * Displays class metadata and the full student roster. Teachers can add
 * students manually, import via CSV, or soft-remove a student from the roster.
 *
 * All server state via React Query. No useEffect+fetch.
 * Security: no student PII in logs or query keys beyond entity IDs.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getClass } from "@/lib/api/classes";
import { RosterList } from "@/components/classes/RosterList";

export default function ClassDetailPage() {
  const { classId } = useParams<{ classId: string }>();

  const {
    data: cls,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["class", classId],
    queryFn: () => getClass(classId),
    enabled: !!classId,
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="mb-6 text-sm text-gray-500">
        <Link
          href="/dashboard/classes"
          className="hover:text-gray-700 underline"
        >
          Classes
        </Link>
        <span aria-hidden="true" className="mx-2">
          /
        </span>
        <span className="text-gray-900">
          {cls?.name ?? (isLoading ? "Loading…" : "Class")}
        </span>
      </nav>

      {/* Class header */}
      {isLoading && (
        <div
          aria-live="polite"
          aria-busy="true"
          className="mb-6 h-10 w-64 animate-pulse rounded-md bg-gray-200"
        />
      )}

      {isError && (
        <p role="alert" className="mb-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load class. Please refresh the page.
        </p>
      )}

      {cls && (
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{cls.name}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {cls.grade_level}
            {cls.academic_year ? ` · ${cls.academic_year}` : ""}
          </p>
        </div>
      )}

      {/* Roster */}
      {classId && <RosterList classId={classId} />}
    </div>
  );
}
