"use client";

/**
 * Breadcrumbs — auto-generated breadcrumb trail for authenticated dashboard pages.
 *
 * Reads the current pathname and resolves entity names from React Query cache
 * so there are zero extra network requests for data already on-screen.
 *
 * Supported routes and their breadcrumb shapes:
 *   /dashboard                                       Worklist
 *   /dashboard/classes                               Classes
 *   /dashboard/classes/new                           Classes / New class
 *   /dashboard/classes/[id]                          Classes / <class name>
 *   /dashboard/classes/[id]/assignments/new          Classes / <class name> / New assignment
 *   /dashboard/assignments/[id]                      Classes / <class name> / <assignment title>
 *   /dashboard/assignments/[id]/review               Classes / <class name> / <assignment title> / Review queue
 *   /dashboard/assignments/[id]/review/[essayId]     Classes / <class name> / <assignment title> / Review
 *   /dashboard/students/[id]                         Worklist / Student profile
 *   /dashboard/interventions                         Interventions
 *   /dashboard/copilot                               Copilot
 *   /dashboard/rubrics                               Rubrics
 *   /dashboard/rubrics/new                           Rubrics / New rubric
 *   /dashboard/rubrics/[id]                          Rubrics / <rubric name>
 *
 * Entity names: pulled from React Query cache via useQueryClient().getQueryData().
 * Falls back to "Loading…" if not yet cached (never triggers a fetch).
 *
 * Not rendered on /dashboard (Worklist home — single-level, no trail needed).
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import type { ClassResponse } from "@/lib/api/classes";
import type { AssignmentDetailResponse } from "@/lib/api/assignments";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Crumb {
  label: string;
  href?: string; // omitted for the last (current) crumb
}

// ---------------------------------------------------------------------------
// Cache name helpers — resolve entity names without extra fetches
// ---------------------------------------------------------------------------

function useQueryClient_() {
  return useQueryClient();
}

function getClassName(qc: ReturnType<typeof useQueryClient_>, classId: string): string {
  const cached = qc.getQueryData<ClassResponse>(["class", classId]);
  return cached?.name ?? "…";
}

function getAssignmentData(
  qc: ReturnType<typeof useQueryClient_>,
  assignmentId: string,
): { title: string; classId: string | null } {
  const cached = qc.getQueryData<AssignmentDetailResponse>(["assignment", assignmentId]);
  return { title: cached?.title ?? "…", classId: cached?.class_id ?? null };
}

// ---------------------------------------------------------------------------
// Route → crumbs resolver
// ---------------------------------------------------------------------------

function resolveCrumbs(
  pathname: string,
  qc: ReturnType<typeof useQueryClient_>,
): Crumb[] | null {
  const seg = pathname.split("/").filter(Boolean); // strip empty strings

  // /dashboard — no trail
  if (seg.length === 1 && seg[0] === "dashboard") return null;

  // /dashboard/classes
  if (seg.length === 2 && seg[1] === "classes") {
    return [{ label: "Classes" }];
  }

  // /dashboard/classes/new
  if (seg.length === 3 && seg[1] === "classes" && seg[2] === "new") {
    return [
      { label: "Classes", href: "/dashboard/classes" },
      { label: "New class" },
    ];
  }

  // /dashboard/classes/[classId]  (and deeper: /assignments/new)
  if (seg.length >= 3 && seg[1] === "classes" && seg[2] !== "new") {
    const classId = seg[2];
    const className = getClassName(qc, classId);

    if (seg.length === 3) {
      return [
        { label: "Classes", href: "/dashboard/classes" },
        { label: className },
      ];
    }

    if (seg.length === 5 && seg[3] === "assignments" && seg[4] === "new") {
      return [
        { label: "Classes", href: "/dashboard/classes" },
        { label: className, href: `/dashboard/classes/${classId}` },
        { label: "New assignment" },
      ];
    }
  }

  // /dashboard/assignments/[assignmentId]  (and deeper review routes)
  if (seg.length >= 3 && seg[1] === "assignments") {
    const assignmentId = seg[2];
    const { title: assignmentTitle, classId } = getAssignmentData(qc, assignmentId);
    const className = classId ? getClassName(qc, classId) : null;

    const classHref = classId ? `/dashboard/classes/${classId}` : "/dashboard/classes";
    const classCrumb: Crumb = className
      ? { label: className, href: classHref }
      : { label: "Classes", href: "/dashboard/classes" };

    // /dashboard/assignments/[id]
    if (seg.length === 3) {
      return [
        { label: "Classes", href: "/dashboard/classes" },
        classCrumb,
        { label: assignmentTitle },
      ];
    }

    // /dashboard/assignments/[id]/review
    if (seg.length === 4 && seg[3] === "review") {
      return [
        { label: "Classes", href: "/dashboard/classes" },
        classCrumb,
        { label: assignmentTitle, href: `/dashboard/assignments/${assignmentId}` },
        { label: "Review queue" },
      ];
    }

    // /dashboard/assignments/[id]/review/[essayId]
    if (seg.length === 5 && seg[3] === "review") {
      return [
        { label: "Classes", href: "/dashboard/classes" },
        classCrumb,
        { label: assignmentTitle, href: `/dashboard/assignments/${assignmentId}` },
        { label: "Review queue", href: `/dashboard/assignments/${assignmentId}/review` },
        { label: "Essay" },
      ];
    }
  }

  // /dashboard/students/[id]
  if (seg.length === 3 && seg[1] === "students") {
    return [
      { label: "Worklist", href: "/dashboard" },
      { label: "Student profile" },
    ];
  }

  // /dashboard/interventions
  if (seg.length === 2 && seg[1] === "interventions") {
    return [{ label: "Interventions" }];
  }

  // /dashboard/copilot
  if (seg.length === 2 && seg[1] === "copilot") {
    return [{ label: "Copilot" }];
  }

  // /dashboard/rubrics
  if (seg.length === 2 && seg[1] === "rubrics") {
    return [{ label: "Rubrics" }];
  }

  // /dashboard/rubrics/new
  if (seg.length === 3 && seg[1] === "rubrics" && seg[2] === "new") {
    return [
      { label: "Rubrics", href: "/dashboard/rubrics" },
      { label: "New rubric" },
    ];
  }

  // /dashboard/rubrics/[id]
  if (seg.length === 3 && seg[1] === "rubrics") {
    return [
      { label: "Rubrics", href: "/dashboard/rubrics" },
      { label: "Rubric" },
    ];
  }

  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Breadcrumbs() {
  const pathname = usePathname();
  const qc = useQueryClient();

  const crumbs = resolveCrumbs(pathname, qc);
  if (!crumbs || crumbs.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className="mb-5 flex items-center gap-1 text-sm text-gray-500">
      {crumbs.map((crumb, idx) => {
        const isLast = idx === crumbs.length - 1;
        return (
          <span key={idx} className="flex items-center gap-1">
            {idx > 0 && (
              <span aria-hidden="true" className="text-gray-300">
                /
              </span>
            )}
            {crumb.href && !isLast ? (
              <Link
                href={crumb.href}
                className="hover:text-gray-800 underline-offset-2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
              >
                {crumb.label}
              </Link>
            ) : (
              <span
                className={isLast ? "font-medium text-gray-900" : ""}
                aria-current={isLast ? "page" : undefined}
              >
                {crumb.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
