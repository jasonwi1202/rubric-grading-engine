"use client";

/**
 * /dashboard/assignments/[assignmentId]/review
 *
 * Review queue page — list view of all essays for teacher triage.
 * M3.22 implementation.
 *
 * Displays all essays in the assignment with status badges, scores, and links
 * to the individual essay review interface (M3.21).
 *
 * Data loading:
 *   1. GET /assignments/{assignmentId}         → assignment metadata + rubric name
 *   2. GET /assignments/{assignmentId}/essays  → essay list with grade summary
 *
 * Security:
 *   - Essay UUIDs are used in URLs; no student names or PII in URL parameters.
 *   - No essay content or student PII in localStorage, sessionStorage, or cookies.
 *   - Error messages never contain raw server text or student data.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getAssignment } from "@/lib/api/assignments";
import { listReviewQueue } from "@/lib/api/essays";
import { ReviewQueue } from "@/components/grading/ReviewQueue";

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function ReviewQueuePage() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const queryClient = useQueryClient();

  const {
    data: assignment,
    isLoading: assignmentLoading,
    isError: assignmentError,
  } = useQuery({
    queryKey: ["assignment", assignmentId],
    queryFn: () => getAssignment(assignmentId),
    enabled: !!assignmentId,
  });

  const {
    data: essays,
    isLoading: essaysLoading,
    isError: essaysError,
  } = useQuery({
    queryKey: ["assignments", assignmentId, "essays", "review-queue"],
    queryFn: () => listReviewQueue(assignmentId),
    enabled: !!assignmentId,
    // Keep reasonably fresh; teacher may have locked grades in the review
    // interface and returned here, so re-fetch often enough to reflect that.
    staleTime: 10_000,
  });

  const isLoading = assignmentLoading || essaysLoading;
  const isError = assignmentError || essaysError;

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
        {assignment?.class_id && (
          <>
            <span aria-hidden="true" className="mx-2">/</span>
            <Link
              href={`/dashboard/classes/${assignment.class_id}`}
              className="hover:text-gray-700 underline"
            >
              Class
            </Link>
          </>
        )}
        <span aria-hidden="true" className="mx-2">/</span>
        {assignment ? (
          <Link
            href={`/dashboard/assignments/${assignmentId}`}
            className="hover:text-gray-700 underline"
          >
            {assignment.title}
          </Link>
        ) : (
          <span>{isLoading ? "Loading\u2026" : "Assignment"}</span>
        )}
        <span aria-hidden="true" className="mx-2">/</span>
        <span className="text-gray-900">Review queue</span>
      </nav>

      {/* Page heading */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          {assignment?.title
            ? `Review queue — ${assignment.title}`
            : isLoading
              ? "Loading\u2026"
              : "Review queue"}
        </h1>
        {assignment && (
          <p className="mt-1 text-sm text-gray-500">
            Rubric: {assignment.rubric_snapshot.name}
          </p>
        )}
      </div>

      {/* Loading skeleton */}
      {isLoading && (
        <div aria-live="polite" aria-busy="true" className="space-y-3">
          <div className="h-8 w-64 animate-pulse rounded-md bg-gray-200" />
          {[1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              className="h-14 animate-pulse rounded-lg bg-gray-200"
            />
          ))}
        </div>
      )}

      {/* Error state */}
      {isError && !isLoading && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {essaysError
            ? "Failed to load essays. Please refresh the page."
            : "Failed to load assignment. Please refresh the page."}
        </p>
      )}

      {/* Review queue */}
      {!isLoading && !isError && essays && (
        <ReviewQueue
          essays={essays}
          assignmentId={assignmentId}
          onBulkApproveSuccess={() => {
            queryClient.invalidateQueries({
              queryKey: ["assignments", assignmentId, "essays", "review-queue"],
            });
          }}
        />
      )}
    </div>
  );
}
