"use client";

/**
 * LessonPlanningPanel — class-level "what should I teach?" surface.
 *
 * Aggregates skill gap data from GET /classes/{id}/insights to answer
 * the question "what do I teach tomorrow?" without requiring the teacher
 * to mentally assemble it from the heatmap and groups tabs separately.
 *
 * Shows:
 *   - Top skill gaps ranked by affected student count
 *   - A horizontal bar showing proportion of class affected
 *   - "View group" link → Groups tab (filtered to that skill)
 *   - Placeholder for future direct lesson-plan generation
 *
 * Zero new API endpoints — all data from existing insights endpoint.
 *
 * Security: no student PII rendered; only aggregate class-level data.
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getClassInsights } from "@/lib/api/classes";
import type { CommonIssue } from "@/lib/api/classes";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format a normalised score [0,1] as a human-readable percentage string.
 */
function fmtPct(score: number): string {
  return `${Math.round(score * 100)}%`;
}

/**
 * Format a snake_case skill key as a readable label.
 * e.g. "thesis_clarity" → "Thesis Clarity"
 */
function formatSkillKey(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SkillGapRow({
  issue,
  studentCount,
  classId,
}: {
  issue: CommonIssue;
  studentCount: number;
  classId: string;
}) {
  const pct = studentCount > 0 ? issue.affected_student_count / studentCount : 0;
  const barPct = Math.round(pct * 100);
  const label = formatSkillKey(issue.skill_dimension);
  const avgPct = fmtPct(issue.avg_score);

  return (
    <li className="rounded-lg border border-gray-200 bg-white px-5 py-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        {/* Skill name + stats */}
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-gray-900">{label}</p>
          <p className="mt-0.5 text-xs text-gray-500">
            Class average: <span className="font-medium text-gray-700">{avgPct}</span>
            {" · "}
            {issue.affected_student_count} of {studentCount} student
            {studentCount !== 1 ? "s" : ""} below threshold
          </p>

          {/* Proportion bar */}
          <div
            className="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-200"
            role="img"
            aria-label={`${barPct}% of class affected`}
          >
            <div
              className={`h-2 rounded-full transition-all ${
                barPct >= 60
                  ? "bg-red-500"
                  : barPct >= 30
                    ? "bg-yellow-500"
                    : "bg-blue-400"
              }`}
              style={{ width: `${barPct}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-gray-400">{barPct}% of class</p>
        </div>

        {/* Actions */}
        <div className="flex flex-shrink-0 flex-col gap-1.5 text-right">
          <Link
            href={`/dashboard/classes/${classId}?tab=groups&skill=${encodeURIComponent(issue.skill_dimension)}`}
            className="text-xs font-semibold text-blue-600 hover:text-blue-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            View skill group →
          </Link>
        </div>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface LessonPlanningPanelProps {
  classId: string;
}

export function LessonPlanningPanel({ classId }: LessonPlanningPanelProps) {
  const {
    data: insights,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["class-insights", classId],
    queryFn: () => getClassInsights(classId),
    staleTime: 120_000,
    enabled: !!classId,
  });

  if (isLoading) {
    return (
      <div aria-live="polite" aria-busy="true" className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-gray-200" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <p role="alert" className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">
        Failed to load class insights. Please refresh the page.
      </p>
    );
  }

  const issues = insights?.common_issues ?? [];
  const studentCount = insights?.student_count ?? 0;

  if (insights && insights.graded_essay_count === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-10 text-center">
        <p className="text-sm font-medium text-gray-700">No graded essays yet.</p>
        <p className="mt-1 text-xs text-gray-500">
          Lesson planning insights appear after at least one assignment has been graded
          and grades are locked.
        </p>
      </div>
    );
  }

  if (issues.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-10 text-center">
        <p className="text-sm font-medium text-gray-700">No skill gaps detected.</p>
        <p className="mt-1 text-xs text-gray-500">
          All skill averages are above the concern threshold across{" "}
          {insights?.graded_essay_count ?? 0} graded essay
          {(insights?.graded_essay_count ?? 0) !== 1 ? "s" : ""}. Great work!
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="mb-4 text-sm text-gray-500">
        Skill gaps affecting the most students — based on{" "}
        <strong className="text-gray-700">{insights?.graded_essay_count ?? 0}</strong>{" "}
        graded essay{(insights?.graded_essay_count ?? 0) !== 1 ? "s" : ""}. Address
        the top gaps first for the greatest impact.
      </p>

      <ul className="space-y-3" role="list" aria-label="Class skill gaps">
        {issues.map((issue) => (
          <SkillGapRow
            key={issue.skill_dimension}
            issue={issue}
            studentCount={studentCount}
            classId={classId}
          />
        ))}
      </ul>

      {issues.length > 0 && (
        <p className="mt-4 text-xs text-gray-400">
          Tip: Click &ldquo;View skill group&rdquo; to see which students share each gap,
          then use the student profile to generate personalised lesson recommendations.
        </p>
      )}
    </div>
  );
}
