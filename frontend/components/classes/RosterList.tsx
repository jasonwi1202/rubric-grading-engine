"use client";

/**
 * RosterList — displays the enrolled students for a class in a table with
 * controls to add students, import CSV, or remove individual students.
 *
 * All server state is managed via React Query.  No useEffect+fetch.
 *
 * Security: entity IDs (not student names) are used in query keys and
 * mutation payloads.  Student names appear only in the rendered table, not
 * in logs or storage.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listStudents, removeStudent } from "@/lib/api/classes";
import { AddStudentDialog } from "@/components/classes/AddStudentDialog";
import { RemoveStudentDialog } from "@/components/classes/RemoveStudentDialog";
import { CsvImportDialog } from "@/components/classes/CsvImportDialog";
import type { StudentResponse } from "@/lib/api/classes";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RosterListProps {
  classId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RosterList({ classId }: RosterListProps) {
  const queryClient = useQueryClient();

  // Dialogs
  const [showAddStudent, setShowAddStudent] = useState(false);
  const [showCsvImport, setShowCsvImport] = useState(false);
  const [pendingRemove, setPendingRemove] = useState<StudentResponse | null>(
    null,
  );

  // ---- Roster query ----
  const {
    data: students,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["students", classId],
    queryFn: () => listStudents(classId),
  });

  // ---- Remove mutation ----
  const removeMutation = useMutation({
    mutationFn: (studentId: string) => removeStudent(classId, studentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["students", classId] });
      setPendingRemove(null);
    },
    onError: () => {
      // Keep dialog open so the teacher can retry
    },
  });

  const handleStudentAdded = () => {
    void queryClient.invalidateQueries({ queryKey: ["students", classId] });
    setShowAddStudent(false);
    // Optimistically update class student count
    void queryClient.invalidateQueries({ queryKey: ["class", classId] });
  };

  const handleCsvImported = () => {
    void queryClient.invalidateQueries({ queryKey: ["students", classId] });
    void queryClient.invalidateQueries({ queryKey: ["class", classId] });
  };

  // ---- Render states ----
  if (isLoading) {
    return (
      <div
        aria-live="polite"
        aria-busy="true"
        className="py-8 text-center text-sm text-gray-500"
      >
        Loading roster…
      </div>
    );
  }

  if (isError) {
    return (
      <p role="alert" className="py-4 text-sm text-red-600">
        Failed to load roster. Please refresh the page.
      </p>
    );
  }

  const activeStudents = (students ?? []).filter((s) => s.is_active);

  return (
    <section aria-labelledby="roster-heading">
      {/* Header row */}
      <div className="mb-4 flex items-center justify-between">
        <h2 id="roster-heading" className="text-base font-semibold text-gray-900">
          Students{" "}
          <span className="ml-1 text-sm font-normal text-gray-500">
            ({activeStudents.length})
          </span>
        </h2>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setShowCsvImport(true)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Import CSV
          </button>
          <button
            type="button"
            onClick={() => setShowAddStudent(true)}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
          >
            Add student
          </button>
        </div>
      </div>

      {/* Roster table or empty state */}
      {activeStudents.length === 0 ? (
        <div className="rounded-md border border-dashed border-gray-300 py-12 text-center text-sm text-gray-500">
          No students enrolled yet.{" "}
          <button
            type="button"
            onClick={() => setShowAddStudent(true)}
            className="text-blue-600 underline hover:text-blue-800"
          >
            Add the first student
          </button>{" "}
          or{" "}
          <button
            type="button"
            onClick={() => setShowCsvImport(true)}
            className="text-blue-600 underline hover:text-blue-800"
          >
            import a CSV
          </button>
          .
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs font-medium uppercase text-gray-500">
              <tr>
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">External ID</th>
                <th className="px-4 py-3 text-left">Enrolled</th>
                <th className="px-4 py-3 text-right">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {activeStudents.map((student) => (
                <tr key={student.id}>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {student.full_name}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {student.external_id ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {new Date(student.enrolled_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => setPendingRemove(student)}
                      aria-label={`Remove ${student.full_name}`}
                      className="text-sm text-red-600 hover:text-red-800 focus:outline-none focus:ring-2 focus:ring-red-500 rounded"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Dialogs */}
      <AddStudentDialog
        classId={classId}
        open={showAddStudent}
        onClose={() => setShowAddStudent(false)}
        onAdded={handleStudentAdded}
      />

      <CsvImportDialog
        classId={classId}
        open={showCsvImport}
        onClose={() => setShowCsvImport(false)}
        onImported={handleCsvImported}
      />

      {pendingRemove && (
        <RemoveStudentDialog
          studentName={pendingRemove.full_name}
          open={true}
          onClose={() => setPendingRemove(null)}
          onConfirm={() => removeMutation.mutate(pendingRemove.id)}
          isPending={removeMutation.isPending}
        />
      )}
    </section>
  );
}
