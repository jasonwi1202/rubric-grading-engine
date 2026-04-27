"use client";

/**
 * SkillHeatmap — class-level heatmap of per-student skill scores.
 *
 * Grid layout: students as rows, normalized skill dimensions as columns.
 * Color bands: green ≥70%, yellow 40–69%, red <40%, gray = no data.
 * Sortable by student name or by any skill column.
 * Student names link to individual student profile pages.
 *
 * Data sources:
 *   - GET /classes/{classId}/insights   → skill column headers
 *   - GET /classes/{classId}/students   → enrolled student list
 *   - GET /students/{studentId}         → per-student skill profile (parallel)
 *
 * Security:
 *   - No student PII in query keys — entity IDs only.
 *   - No student data written to localStorage or sessionStorage.
 */

import { useState, useMemo } from "react";
import Link from "next/link";
import { useQuery, useQueries } from "@tanstack/react-query";
import { getClassInsights, listStudents } from "@/lib/api/classes";
import { getStudentWithProfile } from "@/lib/api/students";
import type { SkillDimensionResponse } from "@/lib/api/students";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Normalised score at or above which a skill is "strong" (green). */
const BAND_HIGH = 0.7;
/** Normalised score at or above which a skill is "developing" (yellow). */
const BAND_MID = 0.4;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type SortKey = "student" | string;
type SortDir = "asc" | "desc";

/**
 * Returns Tailwind classes for the cell chip based on normalised score.
 * Accepts null for "no data" cells.
 */
function scoreBandClasses(score: number | null): string {
  if (score === null) return "bg-gray-100 text-gray-400";
  if (score >= BAND_HIGH) return "bg-green-100 text-green-800";
  if (score >= BAND_MID) return "bg-yellow-100 text-yellow-700";
  return "bg-red-100 text-red-700";
}

function formatPct(score: number): string {
  return `${Math.round(score * 100)}%`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Legend row displayed above the heatmap grid. */
function HeatmapLegend() {
  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-3 text-xs text-gray-600"
      aria-label="Heatmap colour legend"
    >
      <span className="font-medium">Score bands:</span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-3 w-3 rounded-sm bg-green-200"
          aria-hidden="true"
        />
        ≥70% (strong)
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-3 w-3 rounded-sm bg-yellow-200"
          aria-hidden="true"
        />
        40–69% (developing)
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-3 w-3 rounded-sm bg-red-200"
          aria-hidden="true"
        />
        &lt;40% (needs support)
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-3 w-3 rounded-sm bg-gray-200"
          aria-hidden="true"
        />
        No data
      </span>
    </div>
  );
}

/** Skeleton rows shown while data is loading. */
function HeatmapSkeleton() {
  return (
    <div aria-live="polite" aria-busy="true" className="space-y-2 py-4">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="h-10 animate-pulse rounded bg-gray-200" />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SkillHeatmapProps {
  classId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Skill heatmap grid for a single class.
 * Shows each enrolled student's per-skill performance across columns.
 */
export function SkillHeatmap({ classId }: SkillHeatmapProps) {
  const [sortKey, setSortKey] = useState<SortKey>("student");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  // ---- Class insights → skill column headers ----
  const {
    data: insights,
    isLoading: insightsLoading,
    isError: insightsError,
  } = useQuery({
    queryKey: ["class-insights", classId],
    queryFn: () => getClassInsights(classId),
    enabled: !!classId,
  });

  // ---- Enrolled students → row list ----
  const {
    data: students,
    isLoading: studentsLoading,
    isError: studentsError,
  } = useQuery({
    queryKey: ["students", classId],
    queryFn: () => listStudents(classId),
    enabled: !!classId,
  });

  const hasGradedData = (insights?.graded_essay_count ?? 0) > 0;

  // ---- Per-student profiles (parallel) → cell values ----
  const profileQueries = useQueries({
    queries: (students ?? []).map((enrolled) => ({
      queryKey: ["student", enrolled.student.id],
      queryFn: () => getStudentWithProfile(enrolled.student.id),
      // Only fetch profiles once we know there is graded data to display.
      enabled: !!students && hasGradedData,
    })),
  });

  // ---- Derived state ----
  const isLoading = insightsLoading || studentsLoading;
  const isError = insightsError || studentsError;

  /** Sorted canonical skill names used as column headers. */
  const skillColumns = useMemo<string[]>(() => {
    if (!insights) return [];
    return Object.keys(insights.skill_averages).sort();
  }, [insights]);

  /** Row objects: student id, name, and per-skill dimension map. */
  const rows = useMemo(() => {
    if (!students) return [];
    return students.map((enrolled, index) => {
      const profileData = profileQueries[index]?.data;
      const skills: Record<string, SkillDimensionResponse> | null =
        profileData?.skill_profile?.skill_scores ?? null;
      return {
        studentId: enrolled.student.id,
        studentName: enrolled.student.full_name,
        skills,
      };
    });
  }, [students, profileQueries]);

  /** Apply current sort to the rows. */
  const sortedRows = useMemo(() => {
    if (!rows.length) return rows;
    return [...rows].sort((a, b) => {
      let cmp = 0;
      if (sortKey === "student") {
        cmp = a.studentName.localeCompare(b.studentName);
      } else {
        const aScore = a.skills?.[sortKey]?.avg_score ?? -1;
        const bScore = b.skills?.[sortKey]?.avg_score ?? -1;
        cmp = aScore - bScore;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [rows, sortKey, sortDir]);

  // Toggle sort: clicking an already-active column reverses direction; clicking a
  // new column resets to ascending.
  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sortIndicator = (key: SortKey): string => {
    if (sortKey !== key) return "↕";
    return sortDir === "asc" ? "↑" : "↓";
  };

  // ---- Render: loading ----
  if (isLoading) {
    return <HeatmapSkeleton />;
  }

  // ---- Render: error ----
  if (isError) {
    return (
      <p
        role="alert"
        className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        Failed to load skill heatmap. Please refresh the page.
      </p>
    );
  }

  // ---- Render: empty — no locked grades yet ----
  if (!hasGradedData) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
        <p className="text-sm text-gray-500">
          No skill data yet. The heatmap appears after at least one assignment
          has been graded and locked.
        </p>
      </div>
    );
  }

  // ---- Render: no skill dimensions (shouldn't happen if hasGradedData, but guard) ----
  if (!skillColumns.length) {
    return (
      <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
        <p className="text-sm text-gray-500">No skill dimensions found.</p>
      </div>
    );
  }

  // ---- Render: heatmap grid ----
  return (
    <div>
      <HeatmapLegend />

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table
          className="min-w-full text-sm"
          role="grid"
          aria-label="Class skill heatmap"
        >
          <thead className="bg-gray-50">
            <tr>
              {/* Student name column header */}
              <th
                scope="col"
                className="sticky left-0 z-10 bg-gray-50 px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500"
              >
                <button
                  type="button"
                  onClick={() => handleSort("student")}
                  className="flex items-center gap-1 rounded hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  aria-label={`Sort by student name, currently ${sortKey === "student" ? (sortDir === "asc" ? "ascending" : "descending") : "unsorted"}`}
                >
                  Student
                  <span aria-hidden="true" className="tabular-nums">
                    {sortIndicator("student")}
                  </span>
                </button>
              </th>

              {/* Per-skill column headers */}
              {skillColumns.map((skill) => (
                <th
                  key={skill}
                  scope="col"
                  className="px-3 py-3 text-center text-xs font-semibold uppercase text-gray-500"
                >
                  <button
                    type="button"
                    onClick={() => handleSort(skill)}
                    className="flex w-full items-center justify-center gap-1 rounded hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    aria-label={`Sort by ${skill} score, currently ${sortKey === skill ? (sortDir === "asc" ? "ascending" : "descending") : "unsorted"}`}
                  >
                    <span className="capitalize">{skill.replace(/_/g, " ")}</span>
                    <span aria-hidden="true" className="tabular-nums">
                      {sortIndicator(skill)}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="divide-y divide-gray-100 bg-white">
            {sortedRows.map((row) => (
              <tr key={row.studentId} className="hover:bg-gray-50">
                {/* Student name → link to profile */}
                <td className="sticky left-0 bg-inherit px-4 py-2 font-medium text-gray-900">
                  <Link
                    href={`/dashboard/students/${row.studentId}`}
                    className="rounded text-blue-700 underline hover:text-blue-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {row.studentName}
                  </Link>
                </td>

                {/* Per-skill score cells */}
                {skillColumns.map((skill) => {
                  const dim = row.skills?.[skill];
                  const score = dim?.avg_score ?? null;
                  const pct = score !== null ? formatPct(score) : null;
                  const bandClass = scoreBandClasses(score);
                  const tooltipLabel =
                    pct !== null
                      ? `${row.studentName}: ${skill} = ${pct}`
                      : `${row.studentName}: ${skill} — no data`;

                  return (
                    <td
                      key={skill}
                      className="px-3 py-2 text-center"
                      title={tooltipLabel}
                    >
                      <span
                        className={`inline-block min-w-[3.5rem] rounded px-2 py-1 text-xs font-medium ${bandClass}`}
                        aria-label={pct ?? "No data"}
                      >
                        {pct ?? "—"}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-xs text-gray-400">
        Click a column header to sort by that skill. Click a student name to
        view their full profile.
      </p>
    </div>
  );
}
