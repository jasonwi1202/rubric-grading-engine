"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getOnboardingStatus } from "@/lib/api/onboarding";

/**
 * /onboarding — entry point for the onboarding wizard.
 *
 * Reads the teacher's current onboarding status from the API and redirects
 * to the appropriate step, or to /dashboard if onboarding is already
 * complete.
 *
 * Security: requires a valid JWT (enforced by middleware — unauthenticated
 * visitors are redirected to /login before reaching this page).
 */
export default function OnboardingIndexPage() {
  const router = useRouter();

  useEffect(() => {
    getOnboardingStatus()
      .then(({ completed }) => {
        if (completed) {
          router.replace("/dashboard");
        } else {
          router.replace("/onboarding/class");
        }
      })
      .catch(() => {
        // If the status call fails (e.g. network error), default to step 1.
        router.replace("/onboarding/class");
      });
  }, [router]);

  return (
    <div className="flex flex-1 items-center justify-center">
      <div
        className="h-12 w-12 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600"
        aria-label="Loading…"
        role="status"
      />
    </div>
  );
}
