"use client";

/**
 * CommonIssuesPanel — ranked list of class-wide skill issues.
 *
 * Displays skill dimensions where the class average falls below the concern
 * threshold, ordered by severity (lowest average score first).
 *
 * Each row shows:
 *  - Skill dimension name
 *  - Number of affected students (and percentage of class)
 *  - A proportional bar representing the class average
 *
 * Security: no student PII is rendered — only entity counts and averages.
 */

import type { CommonIssue } from "@/lib/api/classes";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CommonIssuesPanelProps {
  issues: CommonIssue[];
  totalStudentCount: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CommonIssuesPanel({
  issues,
  totalStudentCount,
}: CommonIssuesPanelProps) {
  if (issues.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-6 text-center">
        <p className="text-sm text-gray-500">
          No common issues detected — the class is performing well across all
          skill dimensions.
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="mb-3 text-xs text-gray-500">
        Skills where the class average is below 60%. Ranked by severity (lowest
        average first).
      </p>
      <ul className="space-y-3" role="list" aria-label="Common class issues">
        {issues.map((issue) => {
          const pct = Math.round(issue.avg_score * 100);
          const barColor =
            pct < 40 ? "bg-red-400" : "bg-yellow-400";
          const affectedPct =
            totalStudentCount > 0
              ? Math.round(
                  (issue.affected_student_count / totalStudentCount) * 100,
                )
              : 0;

          return (
            <li
              key={issue.skill_dimension}
              className="rounded-lg border border-gray-200 bg-white p-4"
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="font-medium capitalize text-gray-900">
                  {issue.skill_dimension.replace(/_/g, " ")}
                </span>
                <span className="shrink-0 text-sm text-gray-600">
                  {issue.affected_student_count} of {totalStudentCount} student
                  {totalStudentCount !== 1 ? "s" : ""} ({affectedPct}%)
                </span>
              </div>

              {/* Progress bar */}
              <div
                className="relative h-3 w-full overflow-hidden rounded-full bg-gray-100"
                role="progressbar"
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`${issue.skill_dimension.replace(/_/g, " ")}: class average ${pct}%`}
              >
                <div
                  className={`h-full rounded-full ${barColor} transition-all`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-gray-500">
                Class average: {pct}%
              </p>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
