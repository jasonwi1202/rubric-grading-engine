"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { completeOnboarding } from "@/lib/api/onboarding";

/**
 * /onboarding/done — completion page.
 *
 * Marks the teacher's onboarding as complete on mount (idempotent, so
 * safe to call on repeat visits) and presents a single "Go to my
 * dashboard" CTA.
 *
 * Security: no student PII is collected or displayed here.
 */
export default function OnboardingDonePage() {
  const called = useRef(false);

  useEffect(() => {
    // Call once per mount. Errors are swallowed — the teacher should still
    // be able to navigate to the dashboard even if this call fails.
    if (!called.current) {
      called.current = true;
      completeOnboarding().catch(() => {
        // Best-effort — ignore errors.
      });
    }
  }, []);

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-md rounded-lg bg-white p-8 shadow-md text-center space-y-6">
        <div
          aria-hidden="true"
          className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-green-50 text-4xl"
        >
          🎉
        </div>

        <div className="space-y-2">
          <h1 className="text-3xl font-bold text-gray-900">You&apos;re ready.</h1>
          <p className="text-gray-600">
            Your account is set up. Start by creating an assignment and uploading
            student essays to grade.
          </p>
        </div>

        <div className="rounded-md bg-blue-50 px-4 py-3">
          <p className="text-sm text-blue-800">
            🕐 Your free trial is active. You have 30 days to explore all
            features at no cost.
          </p>
        </div>

        <Link
          href="/dashboard"
          className="block w-full rounded-md bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors"
        >
          Go to my dashboard
        </Link>
      </div>
    </div>
  );
}
