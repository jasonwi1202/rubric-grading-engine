"use client";

/**
 * /dashboard/students/[studentId] — Student skill profile page.
 *
 * Displays:
 * - Student name and enrollment summary
 * - Skill visualization (CSS-based bar chart) of per-dimension scores
 * - Growth indicators (improving / stable / declining) per skill
 * - Auto-identified strengths and gaps
 * - Chronological assignment history with score context
 * - Private teacher notes field (persisted via PATCH /students/{studentId})
 *
 * All server state via React Query. No useEffect+fetch.
 *
 * Security:
 * - No student PII in query keys — uses entity IDs only.
 * - Teacher notes are private; never displayed to students.
 * - No student data written to localStorage or sessionStorage.
 */

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getStudentWithProfile,
  getStudentHistory,
  patchStudent,
} from "@/lib/api/students";
import type {
  SkillDimensionResponse,
  SkillTrend,
  AssignmentHistoryItem,
} from "@/lib/api/students";

// ---------------------------------------------------------------------------
// Helpers — skill display
// ---------------------------------------------------------------------------

const TREND_LABELS: Record<SkillTrend, string> = {
  improving: "Improving ↑",
  stable: "Stable →",
  declining: "Declining ↓",
};

const TREND_COLORS: Record<SkillTrend, string> = {
  improving: "text-green-700",
  stable: "text-gray-500",
  declining: "text-red-600",
};

const TREND_BADGE_COLORS: Record<SkillTrend, string> = {
  improving: "bg-green-50 text-green-700 ring-1 ring-green-200",
  stable: "bg-gray-50 text-gray-600 ring-1 ring-gray-200",
  declining: "bg-red-50 text-red-700 ring-1 ring-red-200",
};

function toPercent(score: number): number {
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}

function formatScore(score: number): string {
  return `${toPercent(score)}%`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/**
 * Single skill bar — label, percentage bar, trend badge.
 * Visually represents avg_score as a horizontal progress bar.
 */
function SkillBar({
  name,
  dimension,
}: {
  name: string;
  dimension: SkillDimensionResponse;
}) {
  const pct = toPercent(dimension.avg_score);
  const barColor =
    pct >= 70
      ? "bg-green-500"
      : pct >= 40
        ? "bg-yellow-400"
        : "bg-red-400";

  return (
    <div className="flex items-center gap-3">
      {/* Skill name */}
      <span className="w-36 shrink-0 text-sm font-medium capitalize text-gray-700">
        {name.replace(/_/g, " ")}
      </span>

      {/* Bar track */}
      <div
        className="relative h-4 flex-1 overflow-hidden rounded-full bg-gray-200"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${name} score: ${pct}%`}
      >
        <div
          className={`h-full rounded-full ${barColor} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Score */}
      <span className="w-10 shrink-0 text-right text-sm tabular-nums text-gray-700">
        {formatScore(dimension.avg_score)}
      </span>

      {/* Trend badge */}
      <span
        className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${TREND_BADGE_COLORS[dimension.trend]}`}
      >
        {TREND_LABELS[dimension.trend]}
      </span>
    </div>
  );
}

/**
 * Loading skeleton for the skill chart section.
 */
function SkillChartSkeleton() {
  return (
    <div aria-busy="true" aria-live="polite" className="space-y-3">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-4 w-36 animate-pulse rounded bg-gray-200" />
          <div className="h-4 flex-1 animate-pulse rounded-full bg-gray-200" />
          <div className="h-4 w-10 animate-pulse rounded bg-gray-200" />
          <div className="h-5 w-20 animate-pulse rounded-full bg-gray-200" />
        </div>
      ))}
    </div>
  );
}

/**
 * History timeline row.
 */
function HistoryRow({ item }: { item: AssignmentHistoryItem }) {
  const pct =
    item.max_possible_score > 0
      ? Math.round((item.total_score / item.max_possible_score) * 100)
      : 0;
  const date = new Date(item.locked_at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

  return (
    <li className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0 flex-1">
        <Link
          href={`/dashboard/assignments/${item.assignment_id}`}
          className="block truncate text-sm font-medium text-blue-700 underline hover:text-blue-900 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
        >
          {item.assignment_title}
        </Link>
        <p className="mt-0.5 text-xs text-gray-500">{date}</p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-sm font-semibold tabular-nums text-gray-900">
          {item.total_score} / {item.max_possible_score}
        </p>
        <p className="text-xs text-gray-500">{pct}%</p>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function StudentProfilePage() {
  const { studentId } = useParams<{ studentId: string }>();
  const queryClient = useQueryClient();

  // ---- Notes local state ----
  const [notesValue, setNotesValue] = useState<string | null>(null);
  const [notesSaved, setNotesSaved] = useState(false);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- Student + profile query ----
  const {
    data: student,
    isLoading: studentLoading,
    isError: studentError,
  } = useQuery({
    queryKey: ["student", studentId],
    queryFn: () => getStudentWithProfile(studentId),
    enabled: !!studentId,
  });

  // Initialize local notes state from server data on first load.
  const notesInitialized = useRef(false);
  useEffect(() => {
    if (student && !notesInitialized.current) {
      notesInitialized.current = true;
      setNotesValue(student.teacher_notes ?? "");
    }
  }, [student]);

  // ---- Assignment history query ----
  const {
    data: history,
    isLoading: historyLoading,
    isError: historyError,
  } = useQuery({
    queryKey: ["student-history", studentId],
    queryFn: () => getStudentHistory(studentId),
    enabled: !!studentId,
  });

  // ---- Notes save mutation ----
  const notesMutation = useMutation({
    mutationFn: (notes: string | null) =>
      patchStudent(studentId, { teacher_notes: notes || null }),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ["student", studentId] });
      setNotesValue(updated.teacher_notes ?? "");
      setNotesSaved(true);
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => setNotesSaved(false), 3000);
    },
    onError: () => {
      // Keep the textarea value — teacher can retry
    },
  });

  const handleSaveNotes = () => {
    notesMutation.mutate(notesValue || null);
  };

  // ---- Derived values ----
  const skillScores = student?.skill_profile?.skill_scores ?? {};
  const skillEntries = Object.entries(skillScores);

  const strengths = skillEntries.filter(
    ([, d]) => d.avg_score >= 0.7 && d.data_points >= 2,
  );
  const gaps = skillEntries.filter(
    ([, d]) => d.avg_score < 0.5 && d.data_points >= 2,
  );

  // Sort skills for display: highest score first
  const sortedSkills = [...skillEntries].sort(
    ([, a], [, b]) => b.avg_score - a.avg_score,
  );

  const hasProfile =
    student?.skill_profile !== null && student?.skill_profile !== undefined;
  const hasHistory = (history?.length ?? 0) > 0;

  // ---- Render ----
  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
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
        <span>
          {studentLoading ? "Loading…" : (student?.full_name ?? "Student")}
        </span>
      </nav>

      {/* ---- Student header ---- */}
      {studentLoading && (
        <div
          aria-live="polite"
          aria-busy="true"
          className="mb-6 h-10 w-64 animate-pulse rounded-md bg-gray-200"
        />
      )}

      {studentError && (
        <p role="alert" className="mb-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load student profile. Please refresh the page.
        </p>
      )}

      {student && (
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-gray-900">
            {student.full_name}
          </h1>
          {student.external_id && (
            <p className="mt-1 text-sm text-gray-500">
              ID: {student.external_id}
            </p>
          )}
        </div>
      )}

      {/* ---- Skill visualization ---- */}
      <section aria-labelledby="skills-heading" className="mb-8">
        <h2
          id="skills-heading"
          className="mb-4 text-base font-semibold text-gray-900"
        >
          Skill Profile
        </h2>

        {studentLoading && <SkillChartSkeleton />}

        {!studentLoading && !studentError && !hasProfile && (
          <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
            <p className="text-sm text-gray-500">
              No skill data yet. Skill profiles are built after at least one
              assignment has been graded and locked.
            </p>
          </div>
        )}

        {hasProfile && (
          <>
            {/* Bar chart */}
            <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
              {sortedSkills.map(([name, dimension]) => (
                <SkillBar key={name} name={name} dimension={dimension} />
              ))}
            </div>

            {/* Strengths and Gaps */}
            {(strengths.length > 0 || gaps.length > 0) && (
              <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                {strengths.length > 0 && (
                  <div
                    className="rounded-lg border border-green-200 bg-green-50 p-4"
                    aria-label="Strengths"
                  >
                    <h3 className="mb-2 text-sm font-semibold text-green-800">
                      Strengths
                    </h3>
                    <ul className="space-y-1">
                      {strengths.map(([name, d]) => (
                        <li
                          key={name}
                          className="flex items-center gap-2 text-sm text-green-700"
                        >
                          <span
                            aria-hidden="true"
                            className={`text-xs ${TREND_COLORS[d.trend]}`}
                          >
                            {d.trend === "improving" ? "↑" : "→"}
                          </span>
                          <span className="capitalize">
                            {name.replace(/_/g, " ")}
                          </span>
                          <span className="ml-auto tabular-nums text-green-600">
                            {formatScore(d.avg_score)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {gaps.length > 0 && (
                  <div
                    className="rounded-lg border border-red-200 bg-red-50 p-4"
                    aria-label="Gaps"
                  >
                    <h3 className="mb-2 text-sm font-semibold text-red-800">
                      Needs Support
                    </h3>
                    <ul className="space-y-1">
                      {gaps.map(([name, d]) => (
                        <li
                          key={name}
                          className="flex items-center gap-2 text-sm text-red-700"
                        >
                          <span
                            aria-hidden="true"
                            className={`text-xs ${TREND_COLORS[d.trend]}`}
                          >
                            {d.trend === "declining" ? "↓" : "→"}
                          </span>
                          <span className="capitalize">
                            {name.replace(/_/g, " ")}
                          </span>
                          <span className="ml-auto tabular-nums text-red-600">
                            {formatScore(d.avg_score)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <p className="mt-2 text-xs text-gray-400">
              Based on {student?.skill_profile?.assignment_count ?? 0}{" "}
              {student?.skill_profile?.assignment_count === 1
                ? "assignment"
                : "assignments"}
            </p>
          </>
        )}
      </section>

      {/* ---- Assignment history ---- */}
      <section aria-labelledby="history-heading" className="mb-8">
        <h2
          id="history-heading"
          className="mb-4 text-base font-semibold text-gray-900"
        >
          Assignment History
        </h2>

        {historyLoading && (
          <div aria-live="polite" aria-busy="true" className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-12 animate-pulse rounded-lg bg-gray-200"
              />
            ))}
          </div>
        )}

        {historyError && (
          <p
            role="alert"
            className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            Failed to load assignment history. Please refresh the page.
          </p>
        )}

        {!historyLoading && !historyError && !hasHistory && (
          <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
            <p className="text-sm text-gray-500">
              No graded assignments yet. History appears after at least one
              assignment has been locked.
            </p>
          </div>
        )}

        {!historyLoading && !historyError && hasHistory && (
          <div className="rounded-lg border border-gray-200 bg-white">
            <ul
              role="list"
              className="divide-y divide-gray-100 px-4"
              aria-label="Assignment history"
            >
              {history!.map((item) => (
                <HistoryRow key={item.grade_id} item={item} />
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* ---- Teacher notes ---- */}
      <section aria-labelledby="notes-heading" className="mb-8">
        <h2
          id="notes-heading"
          className="mb-1 text-base font-semibold text-gray-900"
        >
          Private Notes
        </h2>
        <p className="mb-3 text-xs text-gray-500">
          Only visible to you — never shared with students.
        </p>

        {studentLoading ? (
          <div className="h-24 animate-pulse rounded-lg bg-gray-200" />
        ) : (
          <div className="space-y-2">
            <textarea
              id="teacher-notes"
              aria-label="Private teacher notes"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={5}
              placeholder="Add private notes about this student's progress, instructional priorities, or observations…"
              value={notesValue ?? ""}
              onChange={(e) => {
                setNotesValue(e.target.value);
                setNotesSaved(false);
              }}
              disabled={notesMutation.isPending}
            />

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleSaveNotes}
                disabled={notesMutation.isPending || studentLoading}
                className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {notesMutation.isPending ? "Saving…" : "Save notes"}
              </button>

              {notesSaved && (
                <p role="status" className="text-sm text-green-600">
                  Notes saved.
                </p>
              )}

              {notesMutation.isError && (
                <p role="alert" className="text-sm text-red-600">
                  Failed to save notes. Please try again.
                </p>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
