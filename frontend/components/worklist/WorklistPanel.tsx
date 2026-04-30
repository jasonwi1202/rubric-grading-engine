"use client";

/**
 * WorklistPanel — Teacher worklist UI (M6-06).
 *
 * Displays the prioritized worklist of students who need attention:
 *   - Urgency indicator (1–4, 4 = most urgent) with color-coded badge.
 *   - Trigger reason (persistent gap, regression, non-responder, high inconsistency).
 *   - Suggested action linked to each item.
 *   - Mark done / snooze / dismiss controls per item.
 *   - Filters: action type (trigger), skill gap (skill_key), urgency level.
 *   - Default view: top 10 items by urgency; "Show all" to expand.
 *
 * Data source:
 *   - GET /worklist                       — React Query
 *   - POST /worklist/{id}/complete        — useMutation
 *   - POST /worklist/{id}/snooze          — useMutation
 *   - DELETE /worklist/{id}               — useMutation
 *
 * Security:
 *   - No student PII in query keys — entity IDs only.
 *   - Student IDs from worklist items are used for links only (UUID).
 *   - No student data written to localStorage or sessionStorage.
 */

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getWorklist,
  completeWorklistItem,
  snoozeWorklistItem,
  dismissWorklistItem,
} from "@/lib/api/worklist";
import type { WorklistItem, TriggerType } from "@/lib/api/worklist";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_VISIBLE_COUNT = 10;

const TRIGGER_LABELS: Record<TriggerType, string> = {
  regression: "Score Regression",
  non_responder: "No Improvement After Feedback",
  persistent_gap: "Persistent Skill Gap",
  high_inconsistency: "High Inconsistency",
};

const URGENCY_LABELS: Record<number, string> = {
  1: "Low",
  2: "Medium",
  3: "High",
  4: "Critical",
};

const URGENCY_CLASSES: Record<number, string> = {
  1: "bg-gray-100 text-gray-700",
  2: "bg-blue-100 text-blue-700",
  3: "bg-yellow-100 text-yellow-800",
  4: "bg-red-100 text-red-700",
};

const URGENCY_INDICATOR_CLASSES: Record<number, string> = {
  1: "bg-gray-400",
  2: "bg-blue-500",
  3: "bg-yellow-500",
  4: "bg-red-500",
};

// ---------------------------------------------------------------------------
// Filtering helpers (exported for unit tests)
// ---------------------------------------------------------------------------

export function filterWorklist(
  items: WorklistItem[],
  filters: {
    triggerType: TriggerType | "all";
    skillKey: string | "all";
    urgency: number | "all";
  },
): WorklistItem[] {
  return items.filter((item) => {
    if (filters.triggerType !== "all" && item.trigger_type !== filters.triggerType) {
      return false;
    }
    if (filters.skillKey !== "all") {
      if (filters.skillKey === "__none__") {
        if (item.skill_key !== null) return false;
      } else {
        if (item.skill_key !== filters.skillKey) return false;
      }
    }
    if (filters.urgency !== "all" && item.urgency !== filters.urgency) {
      return false;
    }
    return true;
  });
}

/** Collect unique skill keys from items for the filter dropdown. */
export function extractSkillKeys(items: WorklistItem[]): string[] {
  const keys = new Set<string>();
  for (const item of items) {
    if (item.skill_key) {
      keys.add(item.skill_key);
    }
  }
  return Array.from(keys).sort();
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface WorklistItemCardProps {
  item: WorklistItem;
  onComplete: (id: string) => void;
  onSnooze: (id: string) => void;
  onDismiss: (id: string) => void;
  isPending: boolean;
}

function WorklistItemCard({
  item,
  onComplete,
  onSnooze,
  onDismiss,
  isPending,
}: WorklistItemCardProps) {
  const urgencyLabel = URGENCY_LABELS[item.urgency] ?? String(item.urgency);
  const urgencyClass = URGENCY_CLASSES[item.urgency] ?? "bg-gray-100 text-gray-700";
  const indicatorClass = URGENCY_INDICATOR_CLASSES[item.urgency] ?? "bg-gray-400";
  const triggerLabel = TRIGGER_LABELS[item.trigger_type] ?? item.trigger_type;

  return (
    <li
      className="rounded-lg border border-gray-200 bg-white shadow-sm"
      aria-label={`Worklist item: ${triggerLabel}, urgency ${urgencyLabel}`}
    >
      <div className="flex items-start gap-3 px-4 py-4">
        {/* Urgency indicator dot */}
        <div className="mt-1 flex-shrink-0">
          <span
            className={`block h-3 w-3 rounded-full ${indicatorClass}`}
            aria-hidden="true"
          />
        </div>

        {/* Main content */}
        <div className="min-w-0 flex-1">
          {/* Top row: trigger reason + urgency badge */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-gray-900">{triggerLabel}</span>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${urgencyClass}`}
            >
              {urgencyLabel}
            </span>
            {item.skill_key && (
              <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-medium text-purple-700">
                {item.skill_key}
              </span>
            )}
            {item.status === "snoozed" && (
              <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
                Snoozed
              </span>
            )}
          </div>

          {/* Suggested action */}
          <p className="mt-1 text-sm text-gray-600">{item.suggested_action}</p>

        {/* Student profile link — accessible name uses no PII, only UUID in href */}
          <Link
            href={`/dashboard/students/${item.student_id}`}
            aria-label={`View student profile (ID: ${item.student_id})`}
            className="mt-1 inline-block text-xs font-medium text-blue-600 underline hover:text-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            View student profile →
          </Link>
        </div>

        {/* Action controls */}
        <div className="flex flex-shrink-0 flex-col gap-1 sm:flex-row sm:gap-2">
          <button
            type="button"
            onClick={() => onComplete(item.id)}
            disabled={isPending}
            aria-label="Mark done"
            className="rounded px-2.5 py-1 text-xs font-medium text-green-700 ring-1 ring-green-300 hover:bg-green-50 focus:outline-none focus:ring-2 focus:ring-green-500 disabled:opacity-50"
          >
            Done
          </button>
          <button
            type="button"
            onClick={() => onSnooze(item.id)}
            disabled={isPending}
            aria-label="Snooze item"
            className="rounded px-2.5 py-1 text-xs font-medium text-yellow-700 ring-1 ring-yellow-300 hover:bg-yellow-50 focus:outline-none focus:ring-2 focus:ring-yellow-500 disabled:opacity-50"
          >
            Snooze
          </button>
          <button
            type="button"
            onClick={() => onDismiss(item.id)}
            disabled={isPending}
            aria-label="Dismiss item"
            className="rounded px-2.5 py-1 text-xs font-medium text-gray-600 ring-1 ring-gray-300 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-400 disabled:opacity-50"
          >
            Dismiss
          </button>
        </div>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function WorklistPanel() {
  const queryClient = useQueryClient();

  // ----- Filter state -----
  const [triggerFilter, setTriggerFilter] = useState<TriggerType | "all">("all");
  const [skillFilter, setSkillFilter] = useState<string | "all">("all");
  const [urgencyFilter, setUrgencyFilter] = useState<number | "all">("all");
  const [showAll, setShowAll] = useState(false);

  // ----- Data fetch -----
  const {
    data: worklist,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["worklist"],
    queryFn: getWorklist,
  });

  // ----- Mutations -----
  const completeMutation = useMutation({
    mutationFn: (id: string) => completeWorklistItem(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["worklist"] }),
  });

  const snoozeMutation = useMutation({
    mutationFn: (id: string) => snoozeWorklistItem(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["worklist"] }),
  });

  const dismissMutation = useMutation({
    mutationFn: (id: string) => dismissWorklistItem(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["worklist"] }),
  });

  const isPending =
    completeMutation.isPending || snoozeMutation.isPending || dismissMutation.isPending;

  // ----- Loading -----
  if (isLoading) {
    return (
      <div aria-live="polite" aria-busy="true" className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-gray-200" />
        ))}
      </div>
    );
  }

  // ----- Error -----
  if (isError) {
    return (
      <p
        role="alert"
        className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        Failed to load worklist. Please refresh the page.
      </p>
    );
  }

  const allItems = worklist?.items ?? [];
  const skillKeys = extractSkillKeys(allItems);

  // Apply filters
  const filtered = filterWorklist(allItems, {
    triggerType: triggerFilter,
    skillKey: skillFilter,
    urgency: urgencyFilter,
  });

  // Default top 10
  const visible = showAll ? filtered : filtered.slice(0, DEFAULT_VISIBLE_COUNT);
  const hasMore = filtered.length > DEFAULT_VISIBLE_COUNT && !showAll;

  // ----- Empty state -----
  if (allItems.length === 0) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
        <p className="text-sm font-medium text-gray-700">No items on your worklist.</p>
        <p className="mt-1 text-xs text-gray-500">
          The worklist is generated automatically after assignments are graded. Check
          back once grades are locked.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary line */}
      <p className="text-sm text-gray-500">
        {allItems.length} {allItems.length === 1 ? "item" : "items"} ·{" "}
        {filtered.length} matching filters
      </p>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3" role="group" aria-label="Worklist filters">
        {/* Trigger type filter */}
        <div>
          <label htmlFor="filter-trigger" className="sr-only">
            Filter by action type
          </label>
          <select
            id="filter-trigger"
            value={triggerFilter}
            onChange={(e) => {
              const v = e.target.value;
              const valid: Array<TriggerType | "all"> = [
                "all",
                "regression",
                "non_responder",
                "persistent_gap",
                "high_inconsistency",
              ];
              if (valid.includes(v as TriggerType | "all")) {
                setTriggerFilter(v as TriggerType | "all");
              }
            }}
            className="rounded border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">All action types</option>
            <option value="regression">Score Regression</option>
            <option value="non_responder">No Improvement After Feedback</option>
            <option value="persistent_gap">Persistent Skill Gap</option>
            <option value="high_inconsistency">High Inconsistency</option>
          </select>
        </div>

        {/* Skill gap filter */}
        <div>
          <label htmlFor="filter-skill" className="sr-only">
            Filter by skill gap
          </label>
          <select
            id="filter-skill"
            value={skillFilter}
            onChange={(e) => setSkillFilter(e.target.value)}
            className="rounded border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">All skill gaps</option>
            <option value="__none__">No skill (student-level)</option>
            {skillKeys.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </select>
        </div>

        {/* Urgency filter */}
        <div>
          <label htmlFor="filter-urgency" className="sr-only">
            Filter by urgency
          </label>
          <select
            id="filter-urgency"
            value={urgencyFilter === "all" ? "all" : String(urgencyFilter)}
            onChange={(e) => {
              const v = e.target.value;
              if (v === "all") {
                setUrgencyFilter("all");
              } else {
                const n = Number(v);
                if (n >= 1 && n <= 4) {
                  setUrgencyFilter(n);
                }
              }
            }}
            className="rounded border border-gray-300 bg-white px-2 py-1 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">All urgency levels</option>
            <option value="4">Critical (4)</option>
            <option value="3">High (3)</option>
            <option value="2">Medium (2)</option>
            <option value="1">Low (1)</option>
          </select>
        </div>
      </div>

      {/* Item list */}
      {visible.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-gray-200 p-6 text-center">
          <p className="text-sm text-gray-500">No items match the selected filters.</p>
        </div>
      ) : (
        <ul className="space-y-2" role="list" aria-label="Worklist items">
          {visible.map((item) => (
            <WorklistItemCard
              key={item.id}
              item={item}
              onComplete={(id) => completeMutation.mutate(id)}
              onSnooze={(id) => snoozeMutation.mutate(id)}
              onDismiss={(id) => dismissMutation.mutate(id)}
              isPending={isPending}
            />
          ))}
        </ul>
      )}

      {/* Show more / show fewer */}
      {(hasMore || showAll) && (
        <button
          type="button"
          onClick={() => setShowAll((prev) => !prev)}
          className="text-sm font-medium text-blue-600 underline hover:text-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {showAll
            ? "Show top 10 only"
            : `Show all ${filtered.length} items`}
        </button>
      )}

      {/* Mutation error feedback */}
      {completeMutation.isError && (
        <p role="alert" className="text-xs text-red-600">
          Failed to mark item as done. Please try again.
        </p>
      )}
      {snoozeMutation.isError && (
        <p role="alert" className="text-xs text-red-600">
          Failed to snooze item. Please try again.
        </p>
      )}
      {dismissMutation.isError && (
        <p role="alert" className="text-xs text-red-600">
          Failed to dismiss item. Please try again.
        </p>
      )}
    </div>
  );
}
