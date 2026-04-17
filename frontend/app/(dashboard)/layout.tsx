/**
 * Dashboard layout — wraps all authenticated teacher views.
 *
 * Includes a trial status banner in the header when trial status is available.
 * While the trial is active, it shows remaining days.  Once the trial expires,
 * it renders an explicit "Your trial has ended" banner with an upgrade link.
 */

"use client";

import { useEffect, useState } from "react";
import { getOnboardingStatus } from "@/lib/api/onboarding";

// ---------------------------------------------------------------------------
// Trial banner helpers
// ---------------------------------------------------------------------------

function daysUntil(isoDate: string): number {
  const now = Date.now();
  const end = new Date(isoDate).getTime();
  return Math.max(0, Math.ceil((end - now) / (1000 * 60 * 60 * 24)));
}

function TrialBanner({ trialEndsAt }: { trialEndsAt: string }) {
  const days = daysUntil(trialEndsAt);

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
  const [trialEndsAt, setTrialEndsAt] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    // Best-effort: fetch onboarding status to get trial_ends_at.
    // If this fails (e.g. not yet logged in during SSR hydration), the banner
    // is simply hidden.
    getOnboardingStatus()
      .then(({ trial_ends_at }) => {
        setTrialEndsAt(trial_ends_at);
      })
      .catch(() => {
        // Ignore — trial banner is optional.
      })
      .finally(() => setLoaded(true));
  }, []);

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {loaded && trialEndsAt && <TrialBanner trialEndsAt={trialEndsAt} />}
      <main className="flex-1">{children}</main>
    </div>
  );
}
