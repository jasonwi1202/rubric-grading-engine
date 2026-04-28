"use client";

/**
 * TrendChart — cross-assignment class performance trend.
 *
 * Fetches per-assignment analytics (GET /assignments/{id}/analytics) for each
 * completed/returned assignment in the class and plots the
 * overall_avg_normalized_score as a line chart over time.
 *
 * Rendered using a plain SVG so no charting library is required.
 *
 * Requires at least 2 completed assignments to show data; shows a placeholder
 * message otherwise.
 *
 * Security: no student PII in query keys — assignment IDs only.
 */

import { useQueries } from "@tanstack/react-query";
import { getAssignmentAnalytics } from "@/lib/api/assignments";
import type { AssignmentListItem } from "@/lib/api/assignments";

// ---------------------------------------------------------------------------
// SVG layout constants
// ---------------------------------------------------------------------------

const SVG_WIDTH = 600;
const SVG_HEIGHT = 180;
const PAD_LEFT = 44;
const PAD_RIGHT = 20;
const PAD_TOP = 16;
const PAD_BOTTOM = 44;
const CHART_W = SVG_WIDTH - PAD_LEFT - PAD_RIGHT;
const CHART_H = SVG_HEIGHT - PAD_TOP - PAD_BOTTOM;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Builds an SVG polyline `points` string from an array of x/y pairs. */
function buildPolylinePoints(pts: { x: number; y: number }[]): string {
  return pts.map((p) => `${p.x},${p.y}`).join(" ");
}

/** Truncates a title for display below the axis tick. */
function shortTitle(title: string, maxLen = 10): string {
  return title.length > maxLen ? `${title.slice(0, maxLen - 1)}…` : title;
}

// ---------------------------------------------------------------------------
// Sub-component: skeleton
// ---------------------------------------------------------------------------

function TrendSkeleton() {
  return (
    <div aria-live="polite" aria-busy="true" className="space-y-2 py-4">
      {[1, 2].map((i) => (
        <div key={i} className="h-10 animate-pulse rounded bg-gray-200" />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface TrendChartProps {
  /** All assignments in the class (any status). */
  assignments: AssignmentListItem[];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Plots class-level average score across all completed/returned assignments.
 */
export function TrendChart({ assignments }: TrendChartProps) {
  // Only completed or returned assignments contribute analytics data.
  // Sort ascending by created_at so the x-axis represents time progression.
  const completedAssignments = assignments
    .filter((a) => a.status === "complete" || a.status === "returned")
    .sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );

  // Fetch analytics for each completed assignment in parallel.
  const analyticsQueries = useQueries({
    queries: completedAssignments.map((a) => ({
      queryKey: ["assignment-analytics", a.id],
      queryFn: () => getAssignmentAnalytics(a.id),
      enabled: completedAssignments.length >= 2,
    })),
  });

  // Show skeleton while any query is still loading.
  const isLoading = analyticsQueries.some((q) => q.isLoading);
  const isError = analyticsQueries.some((q) => q.isError);

  if (completedAssignments.length < 2) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-6 text-center">
        <p className="text-sm text-gray-500">
          Cross-assignment trend is available after at least 2 assignments have
          been completed.
        </p>
      </div>
    );
  }

  if (isLoading) {
    return <TrendSkeleton />;
  }

  if (isError) {
    return (
      <p
        role="alert"
        className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        Failed to load assignment analytics. Please refresh the page.
      </p>
    );
  }

  // Build (id, title, normalised score) data points — skip assignments with null scores.
  const dataPoints = completedAssignments
    .map((a, i) => ({
      id: a.id,
      title: a.title,
      score: analyticsQueries[i]?.data?.overall_avg_normalized_score ?? null,
    }))
    .filter(
      (d): d is { id: string; title: string; score: number } =>
        d.score !== null,
    );

  if (dataPoints.length < 2) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-6 text-center">
        <p className="text-sm text-gray-500">
          Not enough graded data yet. At least 2 completed assignments with
          locked grades are needed.
        </p>
      </div>
    );
  }

  // Compute SVG coordinates for each data point.
  const xStep = CHART_W / (dataPoints.length - 1);
  const svgPoints = dataPoints.map((d, i) => ({
    x: PAD_LEFT + i * xStep,
    y: PAD_TOP + CHART_H * (1 - d.score),
  }));

  // Y-axis grid lines at 0%, 25%, 50%, 75%, 100%.
  const yGridLines = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div>
      <svg
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        className="w-full"
        role="img"
        aria-label="Cross-assignment class performance trend chart"
      >
        {/* Y-axis grid lines and labels */}
        {yGridLines.map((val) => {
          const y = PAD_TOP + CHART_H * (1 - val);
          return (
            <g key={val}>
              <line
                x1={PAD_LEFT}
                y1={y}
                x2={PAD_LEFT + CHART_W}
                y2={y}
                stroke="#e5e7eb"
                strokeDasharray="4 3"
              />
              <text
                x={PAD_LEFT - 6}
                y={y + 4}
                textAnchor="end"
                fontSize="10"
                fill="#9ca3af"
              >
                {Math.round(val * 100)}%
              </text>
            </g>
          );
        })}

        {/* Axes */}
        <line
          x1={PAD_LEFT}
          y1={PAD_TOP}
          x2={PAD_LEFT}
          y2={PAD_TOP + CHART_H}
          stroke="#d1d5db"
        />
        <line
          x1={PAD_LEFT}
          y1={PAD_TOP + CHART_H}
          x2={PAD_LEFT + CHART_W}
          y2={PAD_TOP + CHART_H}
          stroke="#d1d5db"
        />

        {/* Trend line */}
        <polyline
          points={buildPolylinePoints(svgPoints)}
          fill="none"
          stroke="#3b82f6"
          strokeWidth="2.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Data-point circles + x-axis labels */}
        {svgPoints.map((pt, i) => {
          const d = dataPoints[i];
          const pct = Math.round(d.score * 100);
          return (
            <g key={i}>
              <circle
                cx={pt.x}
                cy={pt.y}
                r={5}
                fill="#3b82f6"
              >
                <title>{`${d.title}: ${pct}%`}</title>
              </circle>

              {/* Score label above each point */}
              <text
                x={pt.x}
                y={pt.y - 8}
                textAnchor="middle"
                fontSize="10"
                fill="#374151"
                fontWeight="500"
              >
                {pct}%
              </text>

              {/* Assignment title below x-axis */}
              <text
                x={pt.x}
                y={PAD_TOP + CHART_H + 14}
                textAnchor="middle"
                fontSize="9"
                fill="#6b7280"
              >
                {shortTitle(d.title)}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Accessible data table — screen readers see this. */}
      <table className="sr-only" aria-label="Cross-assignment trend data">
        <caption>Overall normalized class average per completed assignment</caption>
        <thead>
          <tr>
            <th scope="col">Assignment</th>
            <th scope="col">Class average</th>
          </tr>
        </thead>
        <tbody>
          {dataPoints.map((d) => (
            <tr key={d.id}>
              <td>{d.title}</td>
              <td>{Math.round(d.score * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="mt-1 text-xs text-gray-400">
        Overall normalized class average per completed assignment. Higher is
        better.
      </p>
    </div>
  );
}
