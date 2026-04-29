"use client";

/**
 * /dashboard/classes/[classId] — class detail with tabbed view.
 *
 * Tabs:
 *   Overview   — assignment list and student roster management
 *   Skill Heatmap — per-student skill score grid (M5.7)
 *   Insights   — class-level skill averages and distributions (M5.6)
 *   Groups     — auto-generated skill-gap groups (M6.3)
 *
 * All server state via React Query. No useEffect+fetch.
 * Security: no student PII in logs or query keys beyond entity IDs.
 */

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getClass } from "@/lib/api/classes";
import { listAssignments, STATUS_LABELS } from "@/lib/api/assignments";
import type { AssignmentStatus } from "@/lib/api/assignments";
import { RosterList } from "@/components/classes/RosterList";
import { SkillHeatmap } from "@/components/classes/SkillHeatmap";
import { ClassInsightsPanel } from "@/components/classes/ClassInsightsPanel";
import { SkillGroupsPanel } from "@/components/classes/SkillGroupsPanel";

const STATUS_COLORS: Record<AssignmentStatus, string> = {
  draft: "bg-gray-100 text-gray-600",
  open: "bg-blue-100 text-blue-700",
  grading: "bg-yellow-100 text-yellow-700",
  review: "bg-orange-100 text-orange-700",
  complete: "bg-green-100 text-green-700",
  returned: "bg-purple-100 text-purple-700",
};

type Tab = "overview" | "heatmap" | "insights" | "groups";

export default function ClassDetailPage() {
  const { classId } = useParams<{ classId: string }>();
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  // Arrow-key navigation between tabs (ARIA tab pattern with roving tabIndex).
  const handleTabKeyDown = (
    e: React.KeyboardEvent<HTMLButtonElement>,
    currentTab: Tab,
  ) => {
    const tabs: Tab[] = ["overview", "heatmap", "insights", "groups"];
    const currentIndex = tabs.indexOf(currentTab);
    let nextIndex = currentIndex;

    if (e.key === "ArrowRight") {
      e.preventDefault();
      nextIndex = (currentIndex + 1) % tabs.length;
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    } else {
      return;
    }

    const nextTab = tabs[nextIndex];
    setActiveTab(nextTab);
    document.getElementById(`tab-${nextTab}`)?.focus();
  };

  const {
    data: cls,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["class", classId],
    queryFn: () => getClass(classId),
    enabled: !!classId,
  });

  const {
    data: assignments,
    isLoading: assignmentsLoading,
    isError: assignmentsError,
  } = useQuery({
    queryKey: ["assignments", classId],
    queryFn: () => listAssignments(classId),
    enabled: !!classId,
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
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
        <span className="text-gray-900">
          {cls?.name ?? (isLoading ? "Loading…" : "Class")}
        </span>
      </nav>

      {/* Class header */}
      {isLoading && (
        <div
          aria-live="polite"
          aria-busy="true"
          className="mb-6 h-10 w-64 animate-pulse rounded-md bg-gray-200"
        />
      )}

      {isError && (
        <p role="alert" className="mb-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to load class. Please refresh the page.
        </p>
      )}

      {cls && (
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{cls.name}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {cls.grade_level}
            {cls.academic_year ? ` · ${cls.academic_year}` : ""}
          </p>
        </div>
      )}

      {/* Tab navigation */}
      <div
        role="tablist"
        aria-label="Class views"
        className="mb-6 flex gap-1 border-b border-gray-200"
      >
        <button
          role="tab"
          type="button"
          aria-selected={activeTab === "overview"}
          aria-controls="tab-panel-overview"
          id="tab-overview"
          tabIndex={activeTab === "overview" ? 0 : -1}
          onClick={() => setActiveTab("overview")}
          onKeyDown={(e) => handleTabKeyDown(e, "overview")}
          className={`px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 rounded-t ${
            activeTab === "overview"
              ? "border-b-2 border-blue-600 text-blue-700"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          Overview
        </button>
        <button
          role="tab"
          type="button"
          aria-selected={activeTab === "heatmap"}
          aria-controls="tab-panel-heatmap"
          id="tab-heatmap"
          tabIndex={activeTab === "heatmap" ? 0 : -1}
          onClick={() => setActiveTab("heatmap")}
          onKeyDown={(e) => handleTabKeyDown(e, "heatmap")}
          className={`px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 rounded-t ${
            activeTab === "heatmap"
              ? "border-b-2 border-blue-600 text-blue-700"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          Skill Heatmap
        </button>
        <button
          role="tab"
          type="button"
          aria-selected={activeTab === "insights"}
          aria-controls="tab-panel-insights"
          id="tab-insights"
          tabIndex={activeTab === "insights" ? 0 : -1}
          onClick={() => setActiveTab("insights")}
          onKeyDown={(e) => handleTabKeyDown(e, "insights")}
          className={`px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 rounded-t ${
            activeTab === "insights"
              ? "border-b-2 border-blue-600 text-blue-700"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          Insights
        </button>
        <button
          role="tab"
          type="button"
          aria-selected={activeTab === "groups"}
          aria-controls="tab-panel-groups"
          id="tab-groups"
          tabIndex={activeTab === "groups" ? 0 : -1}
          onClick={() => setActiveTab("groups")}
          onKeyDown={(e) => handleTabKeyDown(e, "groups")}
          className={`px-4 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 rounded-t ${
            activeTab === "groups"
              ? "border-b-2 border-blue-600 text-blue-700"
              : "text-gray-500 hover:text-gray-700"
          }`}
        >
          Groups
        </button>
      </div>

      {/* Overview tab: assignments + roster */}
      <div
        role="tabpanel"
        id="tab-panel-overview"
        aria-labelledby="tab-overview"
        hidden={activeTab !== "overview"}
      >
        {/* Assignments section */}
        <section aria-labelledby="assignments-heading" className="mb-8">
          <div className="mb-3 flex items-center justify-between">
            <h2
              id="assignments-heading"
              className="text-base font-semibold text-gray-900"
            >
              Assignments
            </h2>
            {classId && (
              <Link
                href={`/dashboard/classes/${classId}/assignments/new`}
                className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
              >
                New assignment
              </Link>
            )}
          </div>

          {assignmentsLoading && (
            <div aria-live="polite" aria-busy="true" className="space-y-2">
              {[1, 2].map((i) => (
                <div
                  key={i}
                  className="h-14 animate-pulse rounded-lg bg-gray-200"
                />
              ))}
            </div>
          )}

          {assignmentsError && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700"
            >
              Failed to load assignments. Please refresh the page.
            </p>
          )}

          {!assignmentsLoading && !assignmentsError && assignments?.length === 0 && (
            <div className="rounded-lg border-2 border-dashed border-gray-200 p-8 text-center">
              <p className="text-sm text-gray-500">
                No assignments yet.{" "}
                <Link
                  href={`/dashboard/classes/${classId}/assignments/new`}
                  className="font-medium text-blue-600 underline hover:text-blue-800"
                >
                  Create the first one
                </Link>
              </p>
            </div>
          )}

          {!assignmentsLoading &&
            !assignmentsError &&
            assignments &&
            assignments.length > 0 && (
              <ul className="space-y-2" role="list">
                {assignments.map((a) => (
                  <li key={a.id}>
                    <Link
                      href={`/dashboard/assignments/${a.id}`}
                      className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-5 py-3 shadow-sm hover:border-blue-300 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 transition-shadow"
                    >
                      <div>
                        <p className="font-semibold text-gray-900">{a.title}</p>
                        <p className="mt-0.5 text-xs text-gray-500">
                          {a.due_date
                            ? `Due ${new Date(a.due_date).toLocaleDateString(undefined, { timeZone: "UTC" })}`
                            : ""}
                        </p>
                      </div>
                      <span
                        className={`ml-4 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[a.status]}`}
                      >
                        {STATUS_LABELS[a.status]}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
        </section>

        {/* Roster */}
        {classId && <RosterList classId={classId} />}
      </div>

      {/* Skill Heatmap tab */}
      <div
        role="tabpanel"
        id="tab-panel-heatmap"
        aria-labelledby="tab-heatmap"
        hidden={activeTab !== "heatmap"}
      >
        <section aria-labelledby="heatmap-heading" className="mb-8">
          <h2
            id="heatmap-heading"
            className="mb-4 text-base font-semibold text-gray-900"
          >
            Skill Heatmap
          </h2>
          {classId && activeTab === "heatmap" && (
            <SkillHeatmap classId={classId} />
          )}
        </section>
      </div>

      {/* Insights tab */}
      <div
        role="tabpanel"
        id="tab-panel-insights"
        aria-labelledby="tab-insights"
        hidden={activeTab !== "insights"}
      >
        <section aria-labelledby="insights-heading" className="mb-8">
          <h2
            id="insights-heading"
            className="mb-4 text-base font-semibold text-gray-900"
          >
            Class Insights
          </h2>
          {classId && activeTab === "insights" && (
            <ClassInsightsPanel
              classId={classId}
              assignments={assignments ?? []}
            />
          )}
        </section>
      </div>

      {/* Groups tab */}
      <div
        role="tabpanel"
        id="tab-panel-groups"
        aria-labelledby="tab-groups"
        hidden={activeTab !== "groups"}
      >
        <section aria-labelledby="groups-heading" className="mb-8">
          <h2
            id="groups-heading"
            className="mb-4 text-base font-semibold text-gray-900"
          >
            Skill-Gap Groups
          </h2>
          {classId && activeTab === "groups" && (
            <SkillGroupsPanel
              classId={classId}
              onNavigateToHeatmap={() => setActiveTab("heatmap")}
            />
          )}
        </section>
      </div>
    </div>
  );
}
