"use client";

/**
 * IntegrityPanel — per-essay academic integrity signals panel (M4.6).
 *
 * Displays:
 * - AI likelihood indicator (low / moderate / high) with percentage
 * - Similarity score with percentage
 * - Flagged passages list (text excerpts that triggered the check)
 * - Teacher status actions: "Mark as reviewed — clear" or "Flag for follow-up"
 * - Current review status badge
 *
 * Design principles:
 * - ALL language is framed as signals, not findings
 *   (e.g. "Potential AI-generated content detected", not "AI content found").
 * - The panel is informational; the teacher always decides next steps.
 * - Locked-state: action buttons are disabled when a terminal status is set;
 *   the teacher can still toggle between reviewed_clear and flagged.
 *
 * Security:
 * - No essay content or student PII is logged.
 * - API error messages are mapped to static strings; raw server text is never shown.
 * - Entity IDs only in error payloads.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { updateIntegrityStatus } from "@/lib/api/integrity";
import type {
  IntegrityReportResponse,
  IntegrityReportStatus,
  FlaggedPassage,
} from "@/lib/api/integrity";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Convert a [0.0, 1.0] score to a percentage string, e.g. "73%".
 * Returns "—" when the value is null or undefined.
 */
function toPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

/**
 * Map ai_likelihood float to a human-readable label.
 * Thresholds are intentionally conservative — language stays as signals.
 */
function aiLikelihoodLabel(value: number | null): string {
  if (value == null) return "Not available";
  if (value < 0.3) return "Low signal";
  if (value < 0.7) return "Moderate signal";
  return "High signal";
}

function aiLikelihoodColor(value: number | null): string {
  if (value == null) return "text-gray-500";
  if (value < 0.3) return "text-green-700";
  if (value < 0.7) return "text-yellow-700";
  return "text-red-700";
}

function aiLikelihoodBg(value: number | null): string {
  if (value == null) return "bg-gray-100";
  if (value < 0.3) return "bg-green-50 border-green-200";
  if (value < 0.7) return "bg-yellow-50 border-yellow-200";
  return "bg-red-50 border-red-200";
}

const STATUS_LABELS: Record<IntegrityReportStatus, string> = {
  pending: "Pending review",
  reviewed_clear: "Reviewed — no concern",
  flagged: "Flagged for follow-up",
};

const STATUS_COLORS: Record<IntegrityReportStatus, string> = {
  pending: "bg-gray-100 text-gray-600",
  reviewed_clear: "bg-green-100 text-green-700",
  flagged: "bg-red-100 text-red-700",
};

function statusErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "FORBIDDEN":
        return "You do not have permission to update this report.";
      case "NOT_FOUND":
        return "Integrity report not found. Please refresh the page.";
      case "VALIDATION_ERROR":
        return "Invalid status value.";
      default:
        return "Failed to update status. Please try again.";
    }
  }
  return "Failed to update status. Please try again.";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ScoreRow({
  label,
  value,
  helpText,
}: {
  label: string;
  value: string;
  helpText?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <div>
        <span className="text-sm text-gray-700">{label}</span>
        {helpText && (
          <p className="text-xs text-gray-400">{helpText}</p>
        )}
      </div>
      <span className="text-sm font-semibold text-gray-900">{value}</span>
    </div>
  );
}

function FlaggedPassageItem({ passage }: { passage: FlaggedPassage }) {
  return (
    <li className="rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2">
      <p className="text-xs italic text-gray-700 line-clamp-3">
        &ldquo;{passage.text}&rdquo;
      </p>
      {passage.ai_probability != null && (
        <p className="mt-1 text-xs text-yellow-700">
          AI signal: {toPercent(passage.ai_probability)}
        </p>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface IntegrityPanelProps {
  /** The integrity report to display. */
  report: IntegrityReportResponse;
  /** Called after a successful status update with the updated report. */
  onStatusUpdate?: (report: IntegrityReportResponse) => void;
}

// ---------------------------------------------------------------------------
// IntegrityPanel
// ---------------------------------------------------------------------------

export function IntegrityPanel({ report, onStatusUpdate }: IntegrityPanelProps) {
  const queryClient = useQueryClient();

  const statusMutation = useMutation({
    mutationFn: (status: "reviewed_clear" | "flagged") =>
      updateIntegrityStatus(report.id, { status }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["integrity", updated.essay_version_id] });
      onStatusUpdate?.(updated);
    },
  });

  const isPending = statusMutation.isPending;

  return (
    <div
      role="region"
      className="rounded-lg border border-gray-200 bg-white shadow-sm"
      aria-label="Academic integrity signals"
    >
      {/* Header */}
      <div className="border-b border-gray-200 px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">
            Integrity Signals
          </h3>
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[report.status]}`}
          >
            {STATUS_LABELS[report.status]}
          </span>
        </div>
        <p className="mt-1 text-xs text-gray-400">
          These are potential signals only. Teacher review is required before any action.
        </p>
      </div>

      <div className="p-4 space-y-4">
        {/* AI likelihood */}
        <div
          className={`rounded-md border px-3 py-2 ${aiLikelihoodBg(report.ai_likelihood)}`}
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-700">
              Potential AI-generated content
            </span>
            <span
              className={`text-sm font-semibold ${aiLikelihoodColor(report.ai_likelihood)}`}
              aria-label={`AI likelihood: ${toPercent(report.ai_likelihood)}`}
            >
              {toPercent(report.ai_likelihood)}
            </span>
          </div>
          <p
            className={`mt-0.5 text-xs ${aiLikelihoodColor(report.ai_likelihood)}`}
          >
            {aiLikelihoodLabel(report.ai_likelihood)}
          </p>
        </div>

        {/* Similarity score */}
        <div className="divide-y divide-gray-100 rounded-md border border-gray-200 px-3">
          <ScoreRow
            label="Potential similarity detected"
            value={toPercent(report.similarity_score)}
            helpText="vs. other submissions in this assignment"
          />
        </div>

        {/* Flagged passages */}
        {report.flagged_passages.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              Passages with potential signals ({report.flagged_passages.length})
            </p>
            <ul className="space-y-2" aria-label="Flagged passages">
              {report.flagged_passages.map((passage, idx) => (
                <FlaggedPassageItem
                  key={idx}
                  passage={passage as FlaggedPassage}
                />
              ))}
            </ul>
          </div>
        )}

        {/* Provider / timestamp */}
        <p className="text-xs text-gray-400">
          Provider: {report.provider} &middot;{" "}
          {new Date(report.created_at).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric",
          })}
        </p>

        {/* Status actions */}
        <div className="border-t border-gray-100 pt-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Teacher action
          </p>

          {statusMutation.isError && (
            <p
              role="alert"
              className="mb-2 text-xs text-red-700"
            >
              {statusErrorMessage(statusMutation.error)}
            </p>
          )}

          <div className="flex flex-col gap-2">
            <button
              type="button"
              disabled={isPending || report.status === "reviewed_clear"}
              onClick={() => statusMutation.mutate("reviewed_clear")}
              className="w-full rounded-md border border-green-300 bg-green-50 px-3 py-2 text-sm font-medium text-green-700 hover:bg-green-100 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Mark as reviewed — no concern"
            >
              {isPending && report.status !== "flagged"
                ? "Saving\u2026"
                : "Mark as reviewed \u2014 no concern"}
            </button>

            <button
              type="button"
              disabled={isPending || report.status === "flagged"}
              onClick={() => statusMutation.mutate("flagged")}
              className="w-full rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Flag for follow-up"
            >
              {isPending && report.status !== "reviewed_clear"
                ? "Saving\u2026"
                : "Flag for follow-up"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// IntegrityPanelSkeleton — shown while loading
// ---------------------------------------------------------------------------

export function IntegrityPanelSkeleton() {
  return (
    <div
      role="region"
      className="rounded-lg border border-gray-200 bg-white shadow-sm animate-pulse"
      aria-busy="true"
      aria-label="Loading integrity signals"
    >
      <div className="border-b border-gray-200 px-4 py-3">
        <div className="h-4 w-40 rounded bg-gray-200" />
      </div>
      <div className="p-4 space-y-3">
        <div className="h-12 rounded-md bg-gray-100" />
        <div className="h-8 rounded-md bg-gray-100" />
        <div className="h-6 w-32 rounded bg-gray-100" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// IntegrityPanelEmpty — shown when no report exists
// ---------------------------------------------------------------------------

export function IntegrityPanelEmpty() {
  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-200 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-900">Integrity Signals</h3>
      </div>
      <div className="p-6 text-center">
        <p className="text-sm text-gray-500">
          No integrity report is available for this essay yet.
        </p>
        <p className="mt-1 text-xs text-gray-400">
          Integrity checks run automatically after essay upload.
        </p>
      </div>
    </div>
  );
}
