"use client";

/**
 * /dashboard/assignments/[assignmentId]/essays
 *
 * Essay input page for a specific assignment.
 *
 * Flow:
 *   1. Teacher clicks "Upload essays" → EssayUploadDialog opens.
 *   2. Teacher clicks "Write in browser" → BrowserWritingInterface opens.
 *   3. After upload/composition, results feed the AutoAssignmentReview.
 *   4. Teacher resolves any unassigned/ambiguous essays.
 *   5. Teacher clicks "Proceed to grading" → navigates to the grading page.
 *
 * All server state via React Query. No useEffect+fetch.
 * Security: no student PII in logs or error messages; entity IDs only.
 */

import { useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listEssays, createComposedEssay } from "@/lib/api/essays";
import { listStudents } from "@/lib/api/classes";
import { EssayUploadDialog } from "@/components/essays/EssayUploadDialog";
import { AutoAssignmentReview } from "@/components/essays/AutoAssignmentReview";
import { BrowserWritingInterface } from "@/components/essays/BrowserWritingInterface";

export default function AssignmentEssaysPage() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [hasUploaded, setHasUploaded] = useState(false);

  // Active browser-composition session; null when the interface is not open.
  const [composingEssayId, setComposingEssayId] = useState<string | null>(null);
  const [composingVersionId, setComposingVersionId] = useState<string | null>(null);

  // Fetch existing essays for this assignment
  const {
    data: essays,
    isLoading: essaysLoading,
    isError: essaysError,
    refetch: refetchEssays,
  } = useQuery({
    queryKey: ["essays", assignmentId],
    queryFn: () => listEssays(assignmentId),
    enabled: !!assignmentId,
  });

  // TODO: the assignment detail endpoint will expose classId once M3.10 is
  // wired in. For now we read it from the URL search params as a temporary
  // mechanism so the roster can be loaded.
  // In practice the teacher arrives here via the class→assignment navigation
  // flow, and classId is available in the query string.
  const classId = searchParams.get("classId") ?? "";

  const {
    data: students,
    isLoading: studentsLoading,
    isError: studentsError,
  } = useQuery({
    queryKey: ["students", classId],
    queryFn: () => listStudents(classId),
    enabled: !!classId,
  });

  // Mutation to start an in-browser composition session
  const { mutate: startCompose, isPending: isStartingCompose, error: composeError } = useMutation({
    mutationFn: () => createComposedEssay(assignmentId),
    onSuccess: (result) => {
      setComposingEssayId(result.essay_id);
      setComposingVersionId(result.essay_version_id);
    },
  });

  const handleUploaded = async () => {
    setHasUploaded(true);
    await refetchEssays();
  };

  const handleCompositionComplete = async () => {
    setComposingEssayId(null);
    setComposingVersionId(null);
    setHasUploaded(true);
    // Invalidate essay list so the newly composed essay appears in the review table.
    // invalidateQueries triggers a refetch automatically for active queries.
    await queryClient.invalidateQueries({ queryKey: ["essays", assignmentId] });
  };

  const handleCompositionCancel = () => {
    setComposingEssayId(null);
    setComposingVersionId(null);
  };

  const handleProceed = () => {
    router.push(
      `/dashboard/assignments/${assignmentId}/grade${classId ? `?classId=${classId}` : ""}`,
    );
  };

  const isLoading = essaysLoading || studentsLoading;
  const showReview =
    hasUploaded || (essays && essays.length > 0);

  // When a composition session is active, render the writing interface instead
  // of the normal page content.
  if (composingEssayId && composingVersionId) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="mb-6 flex items-center gap-4">
          <h1 className="text-2xl font-bold text-gray-900">Write essay</h1>
          <p className="text-sm text-gray-500">
            Your progress is saved automatically every few seconds.
          </p>
        </div>
        <BrowserWritingInterface
          essayId={composingEssayId}
          essayVersionId={composingVersionId}
          onSubmit={handleCompositionComplete}
          onCancel={handleCompositionCancel}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Page header */}
      <div className="mb-6 flex items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-gray-900">Essays</h1>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => startCompose()}
            disabled={isStartingCompose}
            className="rounded-md border border-blue-600 px-4 py-2 text-sm font-semibold text-blue-600 shadow-sm hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          >
            {isStartingCompose ? "Opening\u2026" : "Write in browser"}
          </button>
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Upload essays
          </button>
        </div>
      </div>

      {/* Compose error */}
      {composeError && (
        <p
          role="alert"
          className="mb-4 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Failed to start writing session. Please try again.
        </p>
      )}

      {/* Loading skeleton */}
      {isLoading && (
        <div
          aria-live="polite"
          aria-busy="true"
          className="space-y-3"
        >
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded-md bg-gray-200"
            />
          ))}
        </div>
      )}

      {/* Error state */}
      {essaysError && !isLoading && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Failed to load essays. Please refresh the page.
        </p>
      )}

      {studentsError && !isLoading && (
        <p
          role="alert"
          className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          Failed to load class roster. Manual student assignment is unavailable
          until the page is refreshed.
        </p>
      )}

      {/* Empty state — before first upload */}
      {!isLoading && !essaysError && !showReview && (
        <div className="rounded-lg border-2 border-dashed border-gray-200 p-10 text-center">
          <p className="text-sm text-gray-500">
            No essays yet.{" "}
            <button
              type="button"
              onClick={() => setUploadOpen(true)}
              className="font-medium text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Upload essays
            </button>
            {" "}or{" "}
            <button
              type="button"
              onClick={() => startCompose()}
              disabled={isStartingCompose}
              className="font-medium text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            >
              write directly in the browser
            </button>
            .
          </p>
        </div>
      )}

      {/* Review screen */}
      {!isLoading && !essaysError && showReview && essays && (
        <AutoAssignmentReview
          assignmentId={assignmentId}
          essays={essays}
          students={students ?? []}
          onProceed={handleProceed}
        />
      )}

      {/* Upload dialog */}
      <EssayUploadDialog
        assignmentId={assignmentId}
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={handleUploaded}
      />
    </div>
  );
}

