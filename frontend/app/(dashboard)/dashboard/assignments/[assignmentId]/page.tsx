"use client";

/**
 * /dashboard/assignments/[assignmentId]
 *
 * Assignment overview page.
 *
 * Displays:
 * - Assignment metadata (title, rubric, status badge, due date)
 * - Per-student submission status (pending / submitted / graded / returned)
 * - Status transition controls — only valid next states are offered
 * - Link to upload/manage essays
 *
 * All server state via React Query. No useEffect+fetch.
 * Security: no student essay content displayed in error messages; entity IDs only.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getAssignment,
  updateAssignment,
  VALID_TRANSITIONS,
  TRANSITION_LABELS,
  STATUS_LABELS,
} from "@/lib/api/assignments";
import type { AssignmentStatus, SubmissionStatusItem } from "@/lib/api/assignments";
import { listEssays } from "@/lib/api/essays";
import { getIntegritySummary } from "@/lib/api/integrity";
import { BatchGradingPanel } from "@/components/grading/BatchGradingPanel";
import { ExportPanel } from "@/components/grading/ExportPanel";
import { RegradeQueue } from "@/components/grading/RegradeQueue";
import { parseRubricSnapshot } from "@/lib/rubric/parseRubricSnapshot";

// ---------------------------------------------------------------------------
// Status badge helpers
// ---------------------------------------------------------------------------

const SUBMISSION_STATUS_LABELS: Record<
  SubmissionStatusItem["submission_status"],
  string
> = {
  pending: "Pending",
  submitted: "Submitted",
  graded: "Graded",
  returned: "Returned",
};

const SUBMISSION_STATUS_COLORS: Record<
  SubmissionStatusItem["submission_status"],
  string
> = {
  pending: "bg-gray-100 text-gray-600",
  submitted: "bg-blue-100 text-blue-700",
  graded: "bg-green-100 text-green-700",
  returned: "bg-purple-100 text-purple-700",
};

const ASSIGNMENT_STATUS_COLORS: Record<AssignmentStatus, string> = {
  draft: "bg-gray-100 text-gray-600",
  open: "bg-blue-100 text-blue-700",
  grading: "bg-yellow-100 text-yellow-700",
  review: "bg-orange-100 text-orange-700",
  complete: "bg-green-100 text-green-700",
  returned: "bg-purple-100 text-purple-700",
};

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function AssignmentOverviewPage() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const queryClient = useQueryClient();

  const {
    data: assignment,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["assignment", assignmentId],
    queryFn: () => getAssignment(assignmentId),
    enabled: !!assignmentId,
  });

  // Fetch essays to determine whether any grades are locked.
  // Only enabled once the assignment is loaded and in a state where grades
  // can exist (grading stage or later).
  const { data: essays } = useQuery({
    queryKey: ["assignments", assignmentId, "essays"],
    queryFn: () => listEssays(assignmentId),
    enabled:
      !!assignmentId &&
      !!assignment &&
      !["draft", "open"].includes(assignment.status),
    staleTime: 30_000,
  });

  // Fetch class-level integrity summary — only once grading has started.
  const { data: integritySummary } = useQuery({
    queryKey: ["assignments", assignmentId, "integrity-summary"],
    queryFn: () => getIntegritySummary(assignmentId),
    enabled:
      !!assignmentId &&
      !!assignment &&
      !["draft", "open"].includes(assignment.status),
    staleTime: 60_000,
  });

  // At least one essay has a locked grade → export is available.
  const hasLockedGrades = essays?.some((e) => e.status === "locked") ?? false;

  const transitionMutation = useMutation({
    mutationFn: (nextStatus: AssignmentStatus) =>
      updateAssignment(assignmentId, { status: nextStatus }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["assignment", assignmentId], updated);
      queryClient.invalidateQueries({
        queryKey: ["assignments", updated.class_id],
      });
    },
  });

  const handleTransition = () => {
    if (!assignment) return;
    const next = VALID_TRANSITIONS[assignment.status];
    if (!next) return;
    transitionMutation.mutate(next);
  };

  const nextStatus = assignment
    ? VALID_TRANSITIONS[assignment.status]
    : undefined;
  const transitionLabel = assignment
    ? TRANSITION_LABELS[assignment.status]
    : undefined;

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
        <span className="text-gray-900">
          {assignment?.title ?? (isLoading ? "Loading\u2026" : "Assignment")}
        </span>
      </nav>

      {/* Loading skeleton */}
      {isLoading && (
        <div aria-live="polite" aria-busy="true" className="space-y-4">
          <div className="h-8 w-64 animate-pulse rounded-md bg-gray-200" />
          <div className="h-4 w-40 animate-pulse rounded-md bg-gray-200" />
        </div>
      )}

      {/* Error state */}
      {isError && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Failed to load assignment. Please refresh the page.
        </p>
      )}

      {assignment && (
        <>
          {/* Assignment header */}
          <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-bold text-gray-900">
                  {assignment.title}
                </h1>
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${ASSIGNMENT_STATUS_COLORS[assignment.status]}`}
                >
                  {STATUS_LABELS[assignment.status]}
                </span>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                Rubric: {assignment.rubric_snapshot.name}
                {assignment.due_date
                  ? ` \u00b7 Due ${new Date(assignment.due_date).toLocaleDateString(undefined, { timeZone: "UTC" })}`
                  : ""}
              </p>
            </div>

            {/* Action area */}
            <div className="flex items-center gap-3">
              <Link
                href={`/dashboard/assignments/${assignmentId}/essays?classId=${assignment.class_id}`}
                className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
              >
                Manage essays
              </Link>

              {/* Export options — shown once grading has started */}
              {(assignment.status === "grading" ||
                assignment.status === "review" ||
                assignment.status === "complete" ||
                assignment.status === "returned") && (
                <ExportPanel
                  assignmentId={assignmentId}
                  hasLockedGrades={hasLockedGrades}
                />
              )}

              {/* Review queue — shown once grading has started */}
              {(assignment.status === "grading" ||
                assignment.status === "review" ||
                assignment.status === "complete" ||
                assignment.status === "returned") && (
                <Link
                  href={`/dashboard/assignments/${assignmentId}/review`}
                  className="rounded-md border border-blue-300 bg-blue-50 px-4 py-2 text-sm font-semibold text-blue-700 shadow-sm hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                >
                  Review queue
                </Link>
              )}

              {/* Status transition control — only shown when a next state exists */}
              {nextStatus && transitionLabel && (
                <button
                  type="button"
                  onClick={handleTransition}
                  disabled={transitionMutation.isPending}
                  className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
                  aria-label={`${transitionLabel}, moves to ${STATUS_LABELS[nextStatus]} status`}
                >
                  {transitionMutation.isPending ? "Updating\u2026" : transitionLabel}
                </button>
              )}
            </div>
          </div>

          {/* Transition error */}
          {transitionMutation.isError && (
            <p
              role="alert"
              className="mb-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
            >
              Failed to update assignment status. Please try again.
            </p>
          )}

          {/* Writing prompt (if any) */}
          {assignment.prompt && (
            <div className="mb-6 rounded-md border border-gray-200 bg-gray-50 p-4">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-gray-500">
                Writing prompt
              </p>
              <p className="text-sm text-gray-700 whitespace-pre-wrap">
                {assignment.prompt}
              </p>
            </div>
          )}

          {/* Batch grading panel */}
          <div className="mb-8">
            <BatchGradingPanel
              assignmentId={assignmentId}
              canGrade={
                assignment.status === "open" || assignment.status === "grading"
              }
            />
          </div>

          {/* Integrity signals summary — shown once grading has started */}
          {integritySummary && integritySummary.total > 0 && (
            <section aria-labelledby="integrity-summary-heading" className="mb-8">
              <h2
                id="integrity-summary-heading"
                className="mb-3 text-base font-semibold text-gray-900"
              >
                Integrity signals
              </h2>
              <p className="mb-3 text-xs text-gray-400">
                Potential signals only — teacher review required before any action.
              </p>
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-center">
                  <p className="text-2xl font-bold text-red-700">
                    {integritySummary.flagged}
                  </p>
                  <p className="mt-0.5 text-xs font-medium text-red-600">
                    Flagged
                  </p>
                </div>
                <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-center">
                  <p className="text-2xl font-bold text-gray-700">
                    {integritySummary.pending}
                  </p>
                  <p className="mt-0.5 text-xs font-medium text-gray-500">
                    Pending review
                  </p>
                </div>
                <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-center">
                  <p className="text-2xl font-bold text-green-700">
                    {integritySummary.reviewed_clear}
                  </p>
                  <p className="mt-0.5 text-xs font-medium text-green-600">
                    Reviewed — clear
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* Submission status table */}
          <section aria-labelledby="submission-status-heading">
            <h2
              id="submission-status-heading"
              className="mb-3 text-base font-semibold text-gray-900"
            >
              Student submissions
            </h2>

            {assignment.submission_statuses === undefined ? (
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-6 text-center">
                <p className="text-sm text-gray-500">
                  Submission status is not available yet.{" "}
                  <Link
                    href={`/dashboard/assignments/${assignmentId}/essays?classId=${assignment.class_id}`}
                    className="font-medium text-blue-600 underline hover:text-blue-800"
                  >
                    Manage essays
                  </Link>{" "}
                  to track student progress.
                </p>
              </div>
            ) : assignment.submission_statuses.length === 0 ? (
              <div className="rounded-lg border-2 border-dashed border-gray-200 p-10 text-center">
                <p className="text-sm text-gray-500">
                  No students enrolled in this class yet.
                </p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
                <table
                  className="min-w-full divide-y divide-gray-200"
                  aria-label="Student submission status"
                >
                  <thead className="bg-gray-50">
                    <tr>
                      <th
                        scope="col"
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                      >
                        Student
                      </th>
                      <th
                        scope="col"
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                      >
                        Status
                      </th>
                      <th
                        scope="col"
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500"
                      >
                        Submitted
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {assignment.submission_statuses.map((item) => (
                      <tr key={item.student_id} className="hover:bg-gray-50">
                        <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">
                          {item.student_name}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${SUBMISSION_STATUS_COLORS[item.submission_status]}`}
                          >
                            {SUBMISSION_STATUS_LABELS[item.submission_status]}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                          {item.submitted_at
                            ? new Date(item.submitted_at).toLocaleDateString()
                            : "\u2014"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Regrade request queue — shown once grading has started */}
          {(assignment.status === "grading" ||
            assignment.status === "review" ||
            assignment.status === "complete" ||
            assignment.status === "returned") && (
            <div className="mt-8">
              <RegradeQueue
                assignmentId={assignmentId}
                essays={essays ?? []}
                rubricCriteria={parseRubricSnapshot(
                  assignment.rubric_snapshot as Record<string, unknown>,
                )}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
