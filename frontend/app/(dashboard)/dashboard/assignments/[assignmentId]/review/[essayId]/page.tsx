"use client";

/**
 * /dashboard/assignments/[assignmentId]/review/[essayId]
 *
 * Essay review page — the primary teacher grade-review workflow.
 *
 * Two-panel layout:
 *   Left  — Essay text panel (placeholder until a dedicated API endpoint is
 *            available to serve extracted essay content) + Integrity panel.
 *   Right — Rubric scores + feedback editing panel (EssayReviewPanel).
 *
 * Data loading:
 *   1. GET /assignments/{assignmentId}   → assignment with rubric_snapshot
 *   2. GET /essays/{essayId}/grade       → grade with all criterion scores
 *   3. GET /essays/{essayId}/integrity   → integrity report (404 = no report)
 *
 * The rubric_snapshot provides criterion names, weights, and score ranges
 * that are cross-referenced with the criterion scores by rubric_criterion_id.
 *
 * Security:
 *   - No essay content or student PII in localStorage, sessionStorage, or cookies.
 *   - Error messages never contain raw server text or student data.
 *   - Entity IDs only in any log or error path.
 */

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getAssignment } from "@/lib/api/assignments";
import { getGrade } from "@/lib/api/grades";
import type { GradeResponse } from "@/lib/api/grades";
import { getIntegrityReport } from "@/lib/api/integrity";
import type { IntegrityReportResponse } from "@/lib/api/integrity";
import { getProcessSignals } from "@/lib/api/process-signals";
import { getSnapshots } from "@/lib/api/essays";
import { ApiError } from "@/lib/api/errors";
import {
  EssayReviewPanel,
  type RubricSnapshotCriterion,
} from "@/components/grading/EssayReviewPanel";
import { parseRubricSnapshot } from "@/lib/rubric/parseRubricSnapshot";
import {
  IntegrityPanel,
  IntegrityPanelSkeleton,
  IntegrityPanelEmpty,
} from "@/components/grading/IntegrityPanel";
import {
  WritingProcessPanel,
  WritingProcessPanelSkeleton,
  WritingProcessPanelEmpty,
} from "@/components/grading/WritingProcessPanel";

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function EssayReviewPage() {
  const { assignmentId, essayId } = useParams<{
    assignmentId: string;
    essayId: string;
  }>();
  const queryClient = useQueryClient();

  // Local grade state — updated optimistically after each successful save
  const [localGrade, setLocalGrade] = useState<GradeResponse | null>(null);
  // Local integrity report state — updated after teacher status actions
  const [localIntegrity, setLocalIntegrity] =
    useState<IntegrityReportResponse | null>(null);

  // Load assignment for rubric_snapshot (criterion names/weights)
  const {
    data: assignment,
    isLoading: assignmentLoading,
    isError: assignmentError,
  } = useQuery({
    queryKey: ["assignment", assignmentId],
    queryFn: () => getAssignment(assignmentId),
    enabled: !!assignmentId,
  });

  // Load the essay's grade
  const {
    data: remoteGrade,
    isLoading: gradeLoading,
    isError: gradeError,
  } = useQuery({
    queryKey: ["grade", essayId],
    queryFn: () => getGrade(essayId),
    enabled: !!essayId,
    // Keep data fresh so after a lock the UI re-fetches
    staleTime: 30_000,
  });

  // Load the integrity report — 404 is not an error; it means no report yet.
  const {
    data: remoteIntegrity,
    isLoading: integrityLoading,
  } = useQuery({
    queryKey: ["integrity", essayId],
    queryFn: async () => {
      try {
        return await getIntegrityReport(essayId);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          return null;
        }
        throw err;
      }
    },
    enabled: !!essayId,
    staleTime: 60_000,
  });

  // Load writing process signals — 404 means no report; null means no data.
  const {
    data: processSignals,
    isLoading: processLoading,
  } = useQuery({
    queryKey: ["process-signals", essayId],
    queryFn: async () => {
      try {
        return await getProcessSignals(essayId);
      } catch (err) {
        if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
          return null;
        }
        throw err;
      }
    },
    enabled: !!essayId,
    staleTime: 60_000,
  });

  // Load snapshot metadata for the snapshot viewer — only relevant when
  // process data is available (has_process_data === true).
  const {
    data: snapshotState,
  } = useQuery({
    queryKey: ["snapshots", essayId],
    queryFn: async () => {
      try {
        return await getSnapshots(essayId);
      } catch (err) {
        // 422 = file-upload essay (no snapshot history); treat as no data.
        if (err instanceof ApiError && (err.status === 404 || err.status === 422 || err.status === 403)) {
          return null;
        }
        throw err;
      }
    },
    enabled: !!essayId && processSignals?.has_process_data === true,
    staleTime: 60_000,
  });

  // Effective grade: prefer local optimistic state; fall back to server state
  const grade = localGrade ?? remoteGrade ?? null;
  // Effective integrity report: prefer local after teacher action
  const integrity = localIntegrity ?? remoteIntegrity ?? null;

  const isLoading = assignmentLoading || gradeLoading;
  const isError = assignmentError || gradeError;

  // Parse criteria from rubric_snapshot once the assignment loads
  const criteria: RubricSnapshotCriterion[] = assignment
    ? parseRubricSnapshot(
        assignment.rubric_snapshot as Record<string, unknown>,
      )
    : [];

  const handleGradeUpdate = (updatedGrade: GradeResponse) => {
    setLocalGrade(updatedGrade);
    // Also update the React Query cache so any other consumers see the update
    queryClient.setQueryData(["grade", essayId], updatedGrade);
  };

  const handleIntegrityUpdate = (updatedReport: IntegrityReportResponse) => {
    setLocalIntegrity(updatedReport);
    queryClient.setQueryData(["integrity", essayId], updatedReport);
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb" className="mb-6 text-sm text-gray-500">
        <Link href="/dashboard/classes" className="hover:text-gray-700 underline">
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
        <span className="text-gray-900">Review</span>
      </nav>

      {/* Page heading */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {assignment?.title ?? (isLoading ? "Loading\u2026" : "Essay Review")}
          </h1>
          {assignment && (
            <p className="mt-1 text-sm text-gray-500">
              Rubric: {assignment.rubric_snapshot.name}
            </p>
          )}
        </div>

        {grade?.is_locked && (
          <span className="inline-flex items-center rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-700">
            Locked
          </span>
        )}
      </div>

      {/* Loading skeleton */}
      {isLoading && (
        <div aria-live="polite" aria-busy="true" className="space-y-4">
          <div className="h-8 w-48 animate-pulse rounded-md bg-gray-200" />
          <div className="flex gap-6">
            <div className="flex-1 space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div
                  key={i}
                  className="h-4 animate-pulse rounded-md bg-gray-200"
                />
              ))}
            </div>
            <div className="w-96 space-y-3">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-24 animate-pulse rounded-md bg-gray-200"
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Error state */}
      {isError && !isLoading && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {gradeError
            ? "Failed to load grade. Please refresh the page."
            : "Failed to load assignment. Please refresh the page."}
        </p>
      )}

      {/* Two-panel review layout */}
      {!isLoading && !isError && grade && (
        <div className="flex flex-col gap-6 lg:flex-row">
          {/* Left panel — essay text + integrity */}
          <div className="flex-1 space-y-4 lg:max-w-none">
            <div className="sticky top-8 rounded-lg border border-gray-200 bg-white shadow-sm">
              <div className="border-b border-gray-200 px-4 py-3">
                <h2 className="text-sm font-semibold text-gray-900">
                  Essay
                </h2>
              </div>
              <div className="max-h-[calc(100vh-12rem)] overflow-y-auto p-4">
                {/* Essay text placeholder — a dedicated /essays/{id}/content
                    endpoint is not yet implemented in the API. When it is,
                    replace this placeholder with the fetched text rendered in
                    a <pre> or similar element. */}
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <svg
                    aria-hidden="true"
                    className="mb-4 h-10 w-10 text-gray-300"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>
                  <p className="text-sm font-medium text-gray-500">
                    Essay text preview
                  </p>
                  <p className="mt-1 max-w-xs text-xs text-gray-400">
                    Essay content display is coming soon. Please refer to the
                    original submission file for the full essay text.
                  </p>
                </div>
              </div>
            </div>

            {/* Integrity panel */}
            {integrityLoading ? (
              <IntegrityPanelSkeleton />
            ) : integrity ? (
              <IntegrityPanel
                report={integrity}
                onStatusUpdate={handleIntegrityUpdate}
              />
            ) : (
              <IntegrityPanelEmpty />
            )}

            {/* Writing process panel */}
            {processLoading ? (
              <WritingProcessPanelSkeleton />
            ) : processSignals && processSignals.has_process_data ? (
              <WritingProcessPanel
                signals={processSignals}
                snapshots={snapshotState?.snapshots ?? []}
              />
            ) : processSignals ? (
              <WritingProcessPanelEmpty />
            ) : null}
          </div>

          {/* Right panel — rubric scores + feedback editing */}
          <div className="w-full lg:w-[28rem] xl:w-[32rem]">
            <EssayReviewPanel
              grade={grade}
              criteria={criteria}
              onGradeUpdate={handleGradeUpdate}
            />
          </div>
        </div>
      )}
    </div>
  );
}
