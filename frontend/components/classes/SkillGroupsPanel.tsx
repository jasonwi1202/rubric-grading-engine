"use client";

/**
 * SkillGroupsPanel — Auto-grouping UI (M6-03).
 *
 * Displays the auto-generated skill-gap groups for a class:
 *   - Group list with name (label), shared skill gap (skill_key), and
 *     student count.
 *   - Expandable group rows to reveal individual student members.
 *   - Add/remove student controls for manual group adjustment.
 *   - Stability badges: New / Persistent / Resolved.
 *   - Link to the class Skill Heatmap tab for cross-reference context.
 *   - Empty state when no groups have been computed yet.
 *
 * Data source:
 *   - GET /classes/{classId}/groups   — React Query
 *   - PATCH /classes/{classId}/groups/{groupId}  — useMutation
 *
 * Security:
 *   - No student PII in query keys — entity IDs only.
 *   - No student data written to localStorage or sessionStorage.
 *   - Student names rendered only in the teacher-controlled view.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getClassGroups,
  listStudents,
  updateGroupMembers,
} from "@/lib/api/classes";
import type {
  StudentGroupResponse,
  StudentInGroupResponse,
} from "@/lib/api/classes";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SkillGroupsPanelProps {
  classId: string;
  /** Callback to switch the parent page to the Skill Heatmap tab. */
  onNavigateToHeatmap?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STABILITY_LABELS: Record<string, string> = {
  new: "New",
  persistent: "Persistent",
  exited: "Resolved",
};

const STABILITY_CLASSES: Record<string, string> = {
  new: "bg-blue-100 text-blue-700",
  persistent: "bg-yellow-100 text-yellow-700",
  exited: "bg-green-100 text-green-700",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface GroupCardProps {
  group: StudentGroupResponse;
  classId: string;
  /** All students enrolled in the class, for the "add student" selector. */
  enrolledStudents: { id: string; full_name: string }[];
}

function GroupCard({ group, classId, enrolledStudents }: GroupCardProps) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const currentIds = group.students.map((s) => s.id);

  // Students not already in this group (for the "add" selector).
  const addableStudents = enrolledStudents.filter(
    (s) => !currentIds.includes(s.id),
  );

  const patchMutation = useMutation({
    mutationFn: (studentIds: string[]) =>
      updateGroupMembers(classId, group.id, { student_ids: studentIds }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["class-groups", classId],
      });
      setAddError(null);
      setRemoveError(null);
    },
    onError: () => {
      // Errors surfaced inline via addError / removeError below.
    },
  });

  const handleRemoveStudent = (studentId: string) => {
    const newIds = currentIds.filter((id) => id !== studentId);
    setRemoveError(null);
    patchMutation.mutate(newIds, {
      onError: () =>
        setRemoveError("Failed to remove student. Please try again."),
    });
  };

  const handleAddStudent = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const studentId = e.target.value;
    if (!studentId) return;
    const newIds = [...currentIds, studentId];
    setAddError(null);
    patchMutation.mutate(newIds, {
      onError: () => setAddError("Failed to add student. Please try again."),
    });
    // Reset the select back to the placeholder.
    e.target.value = "";
  };

  const isActive = group.stability !== "exited";

  return (
    <li
      className="rounded-lg border border-gray-200 bg-white shadow-sm"
      aria-label={`Skill group: ${group.label}`}
    >
      {/* Group header row */}
      <div className="flex items-center gap-3 px-4 py-3">
        {/* Expand / collapse toggle */}
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={`group-members-${group.id}`}
          onClick={() => setExpanded((prev) => !prev)}
          className="flex-shrink-0 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          aria-label={expanded ? "Collapse group" : "Expand group"}
        >
          <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
        </button>

        {/* Group name + skill key */}
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-gray-900">{group.label}</p>
          <p className="text-xs text-gray-500">
            Skill gap:{" "}
            <span className="font-medium text-gray-700">{group.skill_key}</span>
          </p>
        </div>

        {/* Student count */}
        <span className="flex-shrink-0 text-sm text-gray-600">
          {group.student_count}{" "}
          {group.student_count === 1 ? "student" : "students"}
        </span>

        {/* Stability badge */}
        <span
          className={`flex-shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            STABILITY_CLASSES[group.stability] ?? "bg-gray-100 text-gray-600"
          }`}
        >
          {STABILITY_LABELS[group.stability] ?? group.stability}
        </span>
      </div>

      {/* Expanded member details */}
      {expanded && (
        <div
          id={`group-members-${group.id}`}
          className="border-t border-gray-100 px-4 pb-4 pt-3"
        >
          {/* Student list */}
          {group.students.length === 0 ? (
            <p className="text-sm text-gray-500">
              No students in this group.
            </p>
          ) : (
            <ul
              className="mb-3 space-y-1"
              aria-label={`Students in ${group.label}`}
            >
              {group.students.map((student: StudentInGroupResponse) => (
                <li
                  key={student.id}
                  className="flex items-center justify-between gap-2 rounded px-2 py-1 hover:bg-gray-50"
                >
                  <span className="text-sm text-gray-800">
                    {student.full_name}
                    {student.external_id && (
                      <span className="ml-1 text-xs text-gray-400">
                        ({student.external_id})
                      </span>
                    )}
                  </span>
                  {isActive && (
                    <button
                      type="button"
                      onClick={() => handleRemoveStudent(student.id)}
                      disabled={patchMutation.isPending}
                      aria-label={`Remove ${student.full_name} from group`}
                      className="flex-shrink-0 rounded px-2 py-0.5 text-xs font-medium text-red-600 hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-400 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {removeError && (
            <p role="alert" className="mb-2 text-xs text-red-600">
              {removeError}
            </p>
          )}

          {/* Add student selector — only for active groups */}
          {isActive && addableStudents.length > 0 && (
            <div className="flex items-center gap-2">
              <label
                htmlFor={`add-student-${group.id}`}
                className="sr-only"
              >
                Add student to {group.label}
              </label>
              <select
                id={`add-student-${group.id}`}
                onChange={handleAddStudent}
                disabled={patchMutation.isPending}
                defaultValue=""
                className="flex-1 rounded border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              >
                <option value="" disabled>
                  Add a student…
                </option>
                {addableStudents.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.full_name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {addError && (
            <p role="alert" className="mt-1 text-xs text-red-600">
              {addError}
            </p>
          )}

          {patchMutation.isPending && (
            <p className="mt-1 text-xs text-gray-400" aria-live="polite">
              Saving…
            </p>
          )}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SkillGroupsPanel({
  classId,
  onNavigateToHeatmap,
}: SkillGroupsPanelProps) {
  // Fetch groups.
  const {
    data: groupsData,
    isLoading: groupsLoading,
    isError: groupsError,
  } = useQuery({
    queryKey: ["class-groups", classId],
    queryFn: () => getClassGroups(classId),
    enabled: !!classId,
  });

  // Fetch enrolled students for the "add student" selectors.
  const { data: enrolledStudents } = useQuery({
    queryKey: ["students", classId],
    queryFn: () => listStudents(classId),
    enabled: !!classId,
  });

  // Map enrolled students to minimal shape used by GroupCard.
  const studentList = (enrolledStudents ?? []).map((e) => ({
    id: e.student.id,
    full_name: e.student.full_name,
  }));

  // ---- Loading ----
  if (groupsLoading) {
    return (
      <div aria-live="polite" aria-busy="true" className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-16 animate-pulse rounded-lg bg-gray-200"
          />
        ))}
      </div>
    );
  }

  // ---- Error ----
  if (groupsError) {
    return (
      <p role="alert" className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">
        Failed to load skill groups. Please refresh the page.
      </p>
    );
  }

  const groups = groupsData?.groups ?? [];
  const activeGroups = groups.filter((g) => g.stability !== "exited");
  const exitedGroups = groups.filter((g) => g.stability === "exited");

  // ---- Empty state ----
  if (groups.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
        <p className="text-sm font-medium text-gray-700">
          No skill groups yet.
        </p>
        <p className="mt-1 text-xs text-gray-500">
          Groups are computed automatically after assignments are graded and
          grades are locked. Check back after the first batch of grades is
          complete.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Cross-reference link to heatmap */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {activeGroups.length} active{" "}
          {activeGroups.length === 1 ? "group" : "groups"} ·{" "}
          {exitedGroups.length} resolved
        </p>
        {onNavigateToHeatmap && (
          <button
            type="button"
            onClick={onNavigateToHeatmap}
            className="text-sm font-medium text-blue-600 underline hover:text-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            View Skill Heatmap →
          </button>
        )}
      </div>

      {/* Active groups */}
      {activeGroups.length > 0 && (
        <section aria-labelledby="active-groups-heading">
          <h3
            id="active-groups-heading"
            className="mb-2 text-sm font-semibold text-gray-700"
          >
            Active Groups
          </h3>
          <ul className="space-y-2" role="list">
            {activeGroups.map((group: StudentGroupResponse) => (
              <GroupCard
                key={group.id}
                group={group}
                classId={classId}
                enrolledStudents={studentList}
              />
            ))}
          </ul>
        </section>
      )}

      {/* Resolved (exited) groups */}
      {exitedGroups.length > 0 && (
        <section aria-labelledby="resolved-groups-heading">
          <h3
            id="resolved-groups-heading"
            className="mb-2 text-sm font-semibold text-gray-500"
          >
            Resolved Groups
          </h3>
          <ul className="space-y-2" role="list">
            {exitedGroups.map((group: StudentGroupResponse) => (
              <GroupCard
                key={group.id}
                group={group}
                classId={classId}
                enrolledStudents={studentList}
              />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
