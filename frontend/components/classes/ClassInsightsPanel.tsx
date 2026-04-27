"use client";

/**
 * ClassInsightsPanel — class-level insights tab content.
 *
 * Fetches GET /classes/{classId}/insights and renders three panels:
 *   1. Common Issues   — skill dimensions below the concern threshold
 *   2. Score Distributions — per-skill histograms with outlier highlighting
 *   3. Cross-Assignment Trend — longitudinal class average over time
 *
 * Uses the same React Query cache key as the SkillHeatmap tab so the two
 * panels share a single network request when both tabs are visited in the
 * same session.
 *
 * Security: no student PII is rendered; all data is class-level aggregates.
 */

import { useQuery } from "@tanstack/react-query";
import { getClassInsights } from "@/lib/api/classes";
import { CommonIssuesPanel } from "@/components/classes/CommonIssuesPanel";
import { ScoreDistributionPanel } from "@/components/classes/ScoreDistributionPanel";
import { TrendChart } from "@/components/classes/TrendChart";
import type { AssignmentListItem } from "@/lib/api/assignments";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ClassInsightsPanelProps {
  classId: string;
  /** Full list of class assignments (used to build the trend chart). */
  assignments: AssignmentListItem[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ClassInsightsPanel({
  classId,
  assignments,
}: ClassInsightsPanelProps) {
  const {
    data: insights,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["class-insights", classId],
    queryFn: () => getClassInsights(classId),
    enabled: !!classId,
  });

  // ---- Loading ----
  if (isLoading) {
    return (
      <div aria-live="polite" aria-busy="true" className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 animate-pulse rounded-lg bg-gray-200" />
        ))}
      </div>
    );
  }

  // ---- Error ----
  if (isError) {
    return (
      <p
        role="alert"
        className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        Failed to load class insights. Please refresh the page.
      </p>
    );
  }

  // ---- Empty: no locked grades yet ----
  if (!insights || insights.graded_essay_count === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
        <p className="text-sm text-gray-500">
          No insight data yet. Insights appear after at least one assignment has
          been graded and locked.
        </p>
      </div>
    );
  }

  // ---- Render ----
  return (
    <div className="space-y-8">
      {/* Common Issues */}
      <section aria-labelledby="common-issues-heading">
        <h3
          id="common-issues-heading"
          className="mb-3 text-base font-semibold text-gray-900"
        >
          Common Issues
        </h3>
        <CommonIssuesPanel
          issues={insights.common_issues}
          totalStudentCount={insights.student_count}
        />
      </section>

      {/* Score Distributions */}
      <section aria-labelledby="score-dist-heading">
        <h3
          id="score-dist-heading"
          className="mb-3 text-base font-semibold text-gray-900"
        >
          Score Distributions
        </h3>
        <ScoreDistributionPanel
          distributions={insights.score_distributions}
          totalStudentCount={insights.student_count}
        />
      </section>

      {/* Cross-Assignment Trend */}
      <section aria-labelledby="trend-heading">
        <h3
          id="trend-heading"
          className="mb-3 text-base font-semibold text-gray-900"
        >
          Cross-Assignment Trend
        </h3>
        <TrendChart assignments={assignments} />
      </section>
    </div>
  );
}
