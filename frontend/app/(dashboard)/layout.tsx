/**
 * Dashboard layout — wraps all authenticated teacher views.
 *
 * Includes a trial status banner in the header when trial status is available.
 * While the trial is active, it shows remaining days.  Once the trial expires,
 * it renders an explicit "Your trial has ended" banner with an upgrade link.
 */

"use client";

import { useEffect, useState } from "react";
import { getTrialStatus } from "@/lib/api/account";
import { ErrorBoundary } from "@/components/layout/ErrorBoundary";

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
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {loaded && daysRemaining !== null && (
        <TrialBanner daysRemaining={daysRemaining} />
      )}
      <main className="flex-1">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
    </div>
  );
}
