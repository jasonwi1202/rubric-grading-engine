/**
 * Dashboard layout — wraps all authenticated teacher views.
 *
 * Structure:
 *   - Persistent DashboardSidebar (desktop: fixed left 220px; mobile: top bar + drawer)
 *   - Trial status banner above main content when trial is active or expired
 *   - Breadcrumbs beneath the banner, above page content
 *   - ErrorBoundary wrapping all page content
 */

"use client";

import { useEffect, useState } from "react";
import { getTrialStatus } from "@/lib/api/account";
import { ErrorBoundary } from "@/components/layout/ErrorBoundary";
import { DashboardSidebar } from "@/components/layout/DashboardSidebar";
import { Breadcrumbs } from "@/components/layout/Breadcrumbs";

// ---------------------------------------------------------------------------
// Trial banner helpers
// ---------------------------------------------------------------------------

function TrialBanner({ daysRemaining }: { daysRemaining: number }) {
  const days = daysRemaining;

  if (days <= 0) {
    return (
      <div
        role="banner"
        aria-live="polite"
        className="bg-red-50 border-b border-red-200 px-4 py-2 text-center text-sm"
      >
        <span className="font-medium text-red-800">Your trial has ended.</span>{" "}
        <a
          href="/pricing"
          className="font-semibold text-red-700 underline hover:text-red-900"
        >
          Upgrade to continue grading
        </a>
      </div>
    );
  }

  const urgency = days <= 7 ? "bg-yellow-50 border-yellow-200" : "bg-blue-50 border-blue-200";
  const textColor = days <= 7 ? "text-yellow-800" : "text-blue-800";
  const linkColor = days <= 7 ? "text-yellow-700 hover:text-yellow-900" : "text-blue-700 hover:text-blue-900";

  return (
    <div
      role="banner"
      aria-live="polite"
      className={`${urgency} border-b px-4 py-2 text-center text-sm`}
    >
      <span className={`font-medium ${textColor}`}>
        Trial: {days} day{days !== 1 ? "s" : ""} remaining
      </span>
      {days <= 7 && (
        <>
          {" "}—{" "}
          <a
            href="/pricing"
            className={`font-semibold underline ${linkColor}`}
          >
            Upgrade now
          </a>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [daysRemaining, setDaysRemaining] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // Best-effort: fetch trial status to get days_remaining.
    // If this fails (e.g. not yet logged in during SSR hydration), the banner
    // is simply hidden.
    getTrialStatus()
      .then(({ days_remaining }) => {
        setDaysRemaining(days_remaining);
      })
      .catch(() => {
        // Ignore — trial banner is optional.
      })
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className="flex min-h-screen bg-gray-50">
      {/* Sidebar — desktop fixed; mobile top bar + drawer */}
      <DashboardSidebar />

      {/* Main content column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Trial banner */}
        {loaded && daysRemaining !== null && (
          <TrialBanner daysRemaining={daysRemaining} />
        )}

        {/* Page content */}
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Breadcrumbs />
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
