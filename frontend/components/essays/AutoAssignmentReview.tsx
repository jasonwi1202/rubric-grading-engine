"use client";

/**
 * AutoAssignmentReview — post-upload auto-assignment review screen.
 *
 * Displays each uploaded essay with its auto-assignment status:
 * - "assigned"   → matched to a student automatically (green)
 * - "ambiguous"  → multiple students matched; teacher must choose (amber)
 * - "unassigned" → no match found; teacher must assign (red)
 *
 * For every essay that is not fully assigned the teacher can pick a student
 * from the class roster before proceeding to grading.
 *
 * Security:
 * - Student names and essay IDs are shown to the teacher only in this
 *   teacher-controlled context.
 * - No student PII is logged or stored in browser storage.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { assignEssay } from "@/lib/api/essays";
import type { EssayListItem } from "@/lib/api/essays";
import type { EnrolledStudentResponse } from "@/lib/api/classes";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Status badge for an essay's auto-assignment outcome. */
function AssignmentStatusBadge({
  status,
}: {
  status: EssayListItem["auto_assign_status"];
}) {
  if (status === "assigned") {
    return (
      <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
        Assigned
      </span>
    );
  }
  if (status === "ambiguous") {
    return (
      <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
        Ambiguous
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
      Unassigned
    </span>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AutoAssignmentReviewProps {
  /** Assignment ID — used to invalidate the essays query after correction. */
  assignmentId: string;
  /** The essays returned from the upload or GET /assignments/{id}/essays. */
  essays: EssayListItem[];
  /** The class roster — used to populate the student picker. */
  students: EnrolledStudentResponse[];
  /**
   * Called when the teacher clicks "Proceed to grading". All must-assign
   * essays are checked; if any are still unassigned the button is disabled.
   */
  onProceed: () => void;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AutoAssignmentReview({
  assignmentId,
  essays,
  students,
  onProceed,
}: AutoAssignmentReviewProps) {
  const queryClient = useQueryClient();

  // Local overrides: essayId → studentId chosen by teacher
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  // Track which essays are currently being saved
  const [savingIds, setSavingIds] = useState<Set<string>>(new Set());
  // Per-essay save errors
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({});

  const { mutate: saveAssignment } = useMutation({
    mutationFn: ({
      essayId,
      studentId,
    }: {
      essayId: string;
      studentId: string;
    }) => assignEssay(essayId, { student_id: studentId }),
    onMutate: ({ essayId }) => {
      setSavingIds((prev) => new Set(prev).add(essayId));
      setSaveErrors((prev) => {
        const next = { ...prev };
        delete next[essayId];
        return next;
      });
    },
    onSuccess: (_, { essayId }) => {
      setSavingIds((prev) => {
        const next = new Set(prev);
        next.delete(essayId);
        return next;
      });
      // Invalidate essay list so parent re-fetches with updated student_id
      void queryClient.invalidateQueries({
        queryKey: ["essays", assignmentId],
      });
    },
    onError: (_, { essayId }) => {
      setSavingIds((prev) => {
        const next = new Set(prev);
        next.delete(essayId);
        return next;
      });
      setSaveErrors((prev) => ({
        ...prev,
        [essayId]: "Failed to save assignment. Please try again.",
      }));
    },
  });

  const handleStudentChange = (essayId: string, studentId: string) => {
    setOverrides((prev) => ({ ...prev, [essayId]: studentId }));
  };

  const handleSave = (essayId: string) => {
    const studentId = overrides[essayId];
    if (!studentId) return;
    saveAssignment({ essayId, studentId });
  };

  // An essay is "resolved" if it was auto-assigned OR the teacher has saved a
  // manual assignment (i.e., it appears in the server-side student_id or the
  // teacher has saved an override for it).
  function isResolved(essay: EssayListItem): boolean {
    if (essay.auto_assign_status === "assigned" && essay.student_id !== null) {
      return true;
    }
    // Teacher has saved a correction (student_id non-null from fresh list)
    if (
      essay.auto_assign_status !== "assigned" &&
      essay.student_id !== null
    ) {
      return true;
    }
    return false;
  }

  const unresolvedCount = essays.filter((e) => !isResolved(e)).length;
  const canProceed = unresolvedCount === 0 && essays.length > 0;

  function needsManualReview(essay: EssayListItem): boolean {
    return (
      essay.auto_assign_status === null ||
      essay.auto_assign_status === "ambiguous" ||
      essay.auto_assign_status === "unassigned"
    );
  }

  // Group essays for display
  const assignedEssays = essays.filter(
    (e) => e.auto_assign_status === "assigned",
  );
  const needsReviewEssays = essays.filter((e) => needsManualReview(e));

  return (
    <div className="space-y-6">
      {/* Header summary */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900">
          Review auto-assignment
        </h2>
        <p className="mt-1 text-sm text-gray-600">
          {assignedEssays.length} of {essays.length} essay
          {essays.length !== 1 ? "s" : ""} were matched automatically.{" "}
          {needsReviewEssays.length > 0 &&
            `${needsReviewEssays.length} require${needsReviewEssays.length === 1 ? "s" : ""} manual assignment.`}
        </p>
      </div>

      {/* Needs-review section */}
      {needsReviewEssays.length > 0 && (
        <section aria-labelledby="needs-review-heading">
          <h3
            id="needs-review-heading"
            className="mb-2 text-sm font-semibold text-gray-700"
          >
            Needs assignment
          </h3>
          <div className="overflow-hidden rounded-lg border border-amber-200 bg-amber-50">
            <table className="w-full text-sm" aria-label="Essays needing assignment">
              <thead className="bg-amber-100 text-xs font-medium uppercase text-amber-700">
                <tr>
                  <th className="px-4 py-2 text-left">Essay</th>
                  <th className="px-4 py-2 text-left">Status</th>
                  <th className="px-4 py-2 text-left">Assign to student</th>
                  <th className="px-4 py-2 text-left" />
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {needsReviewEssays.map((essay) => {
                  const isSaving = savingIds.has(essay.essay_id);
                  const selectedStudentId = overrides[essay.essay_id] ?? "";
                  const alreadySaved =
                    essay.student_id !== null &&
                    essay.auto_assign_status !== "assigned";

                  return (
                    <tr key={essay.essay_id} className="bg-white">
                      <td className="px-4 py-3 text-gray-700">
                        <span className="font-mono text-xs text-gray-400">
                          {essay.essay_id.slice(0, 8)}…
                        </span>
                        <span className="ml-2 text-gray-600">
                          {essay.word_count} words
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <AssignmentStatusBadge
                          status={
                            alreadySaved ? "assigned" : essay.auto_assign_status
                          }
                        />
                      </td>
                      <td className="px-4 py-3">
                        {alreadySaved ? (
                          <span className="text-sm text-gray-600">
                            {essay.student_name ?? "—"}
                          </span>
                        ) : (
                          <select
                            aria-label={`Assign essay ${essay.essay_id.slice(0, 8)} to student`}
                            value={selectedStudentId}
                            onChange={(e) =>
                              handleStudentChange(essay.essay_id, e.target.value)
                            }
                            disabled={isSaving}
                            className="block w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
                          >
                            <option value="">— Select student —</option>
                            {students.map((s) => (
                              <option key={s.student.id} value={s.student.id}>
                                {s.student.full_name}
                              </option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {!alreadySaved && (
                          <button
                            type="button"
                            onClick={() => handleSave(essay.essay_id)}
                            disabled={isSaving || !selectedStudentId}
                            aria-label={`Save assignment for essay ${essay.essay_id.slice(0, 8)}`}
                            className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:opacity-50"
                          >
                            {isSaving ? "Saving…" : "Save"}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Per-essay save errors */}
          {Object.values(saveErrors).length > 0 && (
            <ul role="alert" aria-live="polite" className="mt-2 space-y-1">
              {Object.entries(saveErrors).map(([id, msg]) => (
                <li key={id} className="text-sm text-red-700">
                  {msg}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Auto-assigned section */}
      {assignedEssays.length > 0 && (
        <section aria-labelledby="auto-assigned-heading">
          <h3
            id="auto-assigned-heading"
            className="mb-2 text-sm font-semibold text-gray-700"
          >
            Auto-assigned
          </h3>
          <div className="overflow-hidden rounded-lg border border-gray-200">
            <table className="w-full text-sm" aria-label="Auto-assigned essays">
              <thead className="bg-gray-50 text-xs font-medium uppercase text-gray-500">
                <tr>
                  <th className="px-4 py-2 text-left">Essay</th>
                  <th className="px-4 py-2 text-left">Student</th>
                  <th className="px-4 py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {assignedEssays.map((essay) => (
                  <tr key={essay.essay_id} className="bg-white">
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-gray-400">
                        {essay.essay_id.slice(0, 8)}…
                      </span>
                      <span className="ml-2 text-gray-600">
                        {essay.word_count} words
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {essay.student_name ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <AssignmentStatusBadge status="assigned" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Empty state */}
      {essays.length === 0 && (
        <p className="rounded-md bg-gray-50 px-4 py-3 text-sm text-gray-600">
          No essays uploaded yet.
        </p>
      )}

      {/* Footer action */}
      <div className="flex items-center justify-between border-t border-gray-200 pt-4">
        {!canProceed && unresolvedCount > 0 && (
          <p role="status" className="text-sm text-amber-700">
            {unresolvedCount} essay{unresolvedCount !== 1 ? "s" : ""} still
            need{unresolvedCount === 1 ? "s" : ""} a student assignment.
          </p>
        )}
        {canProceed && (
          <p role="status" className="text-sm text-green-700">
            All essays are assigned.
          </p>
        )}
        <div className="ml-auto">
          <button
            type="button"
            onClick={onProceed}
            disabled={!canProceed}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
          >
            Proceed to grading
          </button>
        </div>
      </div>
    </div>
  );
}
