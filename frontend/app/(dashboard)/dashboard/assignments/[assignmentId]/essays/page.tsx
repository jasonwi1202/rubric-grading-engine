"use client";

/**
 * /dashboard/assignments/[assignmentId]/essays
 *
 * Essay input page for a specific assignment.
 *
 * Flow:
 *   1. Teacher clicks "Upload essays" → EssayUploadDialog opens.
 *   2. After upload, uploaded results feed the AutoAssignmentReview.
 *   3. Teacher resolves any unassigned/ambiguous essays.
 *   4. Teacher clicks "Proceed to grading" → navigates to the grading page.
 *
 * All server state via React Query. No useEffect+fetch.
 * Security: no student PII in logs or error messages; entity IDs only.
 */

import { useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { listEssays } from "@/lib/api/essays";
import { listStudents } from "@/lib/api/classes";
import { EssayUploadDialog } from "@/components/essays/EssayUploadDialog";
import { AutoAssignmentReview } from "@/components/essays/AutoAssignmentReview";

export default function AssignmentEssaysPage() {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [uploadOpen, setUploadOpen] = useState(false);
  // After an upload, we merge server results into the review list via a refetch
  const [hasUploaded, setHasUploaded] = useState(false);

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
  } = useQuery({
    queryKey: ["students", classId],
    queryFn: () => listStudents(classId),
    enabled: !!classId,
  });

  const handleUploaded = async () => {
    setHasUploaded(true);
    await refetchEssays();
  };

  const handleProceed = () => {
    router.push(
      `/dashboard/assignments/${assignmentId}/grade${classId ? `?classId=${classId}` : ""}`,
    );
  };

  const isLoading = essaysLoading || studentsLoading;
  const showReview =
    hasUploaded || (essays && essays.length > 0);

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Page header */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Essays</h1>
        <button
          type="button"
          onClick={() => setUploadOpen(true)}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Upload essays
        </button>
      </div>

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

      {/* Empty state — before first upload */}
      {!isLoading && !essaysError && !showReview && (
        <div className="rounded-lg border-2 border-dashed border-gray-200 p-10 text-center">
          <p className="text-sm text-gray-500">
            No essays uploaded yet.{" "}
            <button
              type="button"
              onClick={() => setUploadOpen(true)}
              className="font-medium text-blue-600 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              Upload your first essay
            </button>
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
