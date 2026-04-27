"use client";

/**
 * ScoreDistributionPanel — per-skill score distribution histograms.
 *
 * Renders one histogram per skill dimension using the class-level
 * score_distributions data from ClassInsightsResponse. Each bucket
 * spans a 20-percentage-point range (0–20%, 20–40%, …, 80–100%).
 *
 * Outliers (the lowest and highest buckets, when non-empty) are highlighted
 * with an amber ring to draw teacher attention.
 *
 * Security: no student PII is rendered — only anonymous bucket counts.
 */

import type { ScoreBucket } from "@/lib/api/classes";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** SVG bar chart fixed height (px). */
const BAR_MAX_HEIGHT = 80;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Returns a Tailwind background-colour class for a histogram bar based on
 * the lower bound of its percentage-range label (e.g. "20-40%" → 20).
 */
function barColorForLabel(label: string): string {
  const lower = parseInt(label, 10);
  if (isNaN(lower)) return "bg-gray-300";
  if (lower < 40) return "bg-red-400";
  if (lower < 60) return "bg-yellow-400";
  return "bg-green-400";
}

/**
 * Determines if a bucket is an outlier bucket:
 *   - The lowest range (0–20%) with at least one student, OR
 *   - The highest range (80–100%) with at least one student.
 */
function isOutlierBucket(label: string, count: number): boolean {
  if (count === 0) return false;
  const lower = parseInt(label, 10);
  return !isNaN(lower) && (lower === 0 || lower >= 80);
}

// ---------------------------------------------------------------------------
// Sub-component: single histogram
// ---------------------------------------------------------------------------

interface DistributionHistogramProps {
  skillDimension: string;
  buckets: ScoreBucket[];
  totalStudentCount: number;
}

function DistributionHistogram({
  skillDimension,
  buckets,
  totalStudentCount,
}: DistributionHistogramProps) {
  const maxCount = Math.max(...buckets.map((b) => b.count), 1);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h4 className="mb-3 text-sm font-semibold capitalize text-gray-900">
        {skillDimension.replace(/_/g, " ")}
      </h4>

      {/* Histogram bars */}
      <div
        className="flex items-end gap-1"
        role="img"
        aria-label={`Score distribution histogram for ${skillDimension.replace(/_/g, " ")}`}
      >
        {buckets.map((bucket) => {
          const height =
            bucket.count > 0
              ? Math.max(
                  Math.round((bucket.count / maxCount) * BAR_MAX_HEIGHT),
                  4,
                )
              : 0;
          const barColor = barColorForLabel(bucket.label);
          const outlier = isOutlierBucket(bucket.label, bucket.count);
          const studentLabel = `${bucket.count} student${bucket.count !== 1 ? "s" : ""}`;

          return (
            <div
              key={bucket.label}
              className="flex flex-1 flex-col items-center gap-0.5"
            >
              {/* Count label above bar */}
              <span className="text-xs font-medium text-gray-600">
                {bucket.count > 0 ? bucket.count : ""}
              </span>

              {/* Bar */}
              <div
                className={`w-full rounded-t ${barColor} ${
                  outlier
                    ? "ring-2 ring-amber-500 ring-offset-1"
                    : ""
                }`}
                style={{
                  height: `${height}px`,
                  minHeight: height > 0 ? "4px" : "0px",
                }}
                title={`${bucket.label}: ${studentLabel}`}
                aria-label={`${bucket.label}: ${studentLabel}`}
              />

              {/* Bucket label below bar */}
              <span className="text-center text-xs leading-tight text-gray-500">
                {bucket.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <p className="mt-2 text-xs text-gray-400">
        {totalStudentCount} student{totalStudentCount !== 1 ? "s" : ""} ·
        Outlier buckets highlighted in amber
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ScoreDistributionPanelProps {
  distributions: Record<string, ScoreBucket[]>;
  totalStudentCount: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Renders per-skill score distribution histograms for a class.
 * Accepts the score_distributions map from ClassInsightsResponse.
 */
export function ScoreDistributionPanel({
  distributions,
  totalStudentCount,
}: ScoreDistributionPanelProps) {
  const skills = Object.keys(distributions).sort();

  if (skills.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-6 text-center">
        <p className="text-sm text-gray-500">
          No distribution data available yet.
        </p>
      </div>
    );
  }

  return (
    <div
      className="grid grid-cols-1 gap-4 sm:grid-cols-2"
      aria-label="Score distributions by skill"
    >
      {skills.map((skill) => (
        <DistributionHistogram
          key={skill}
          skillDimension={skill}
          buckets={distributions[skill]}
          totalStudentCount={totalStudentCount}
        />
      ))}
    </div>
  );
}
