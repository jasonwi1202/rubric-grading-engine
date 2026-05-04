"use client";

/**
 * Interventions dashboard — teacher interventions review page (M8-01).
 *
 * Renders the list of agent-generated intervention recommendations for the
 * authenticated teacher.  Teachers can approve or dismiss each recommendation.
 *
 * The `status` search param is supported so that worklist items can link here
 * with a preserved filter context (e.g. /dashboard/interventions?status=all).
 *
 * Security: no student PII in logs or query keys beyond entity IDs.
 */

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { InterventionsPanel } from "@/components/interventions/InterventionsPanel";
import type { InterventionStatusFilter } from "@/lib/api/interventions";

const VALID_STATUS_FILTERS: InterventionStatusFilter[] = [
  "pending_review",
  "approved",
  "dismissed",
  "all",
];

function InterventionsPageContent() {
  const searchParams = useSearchParams();
  const rawStatus = searchParams.get("status");
  const initialStatus: InterventionStatusFilter =
    rawStatus !== null &&
    VALID_STATUS_FILTERS.includes(rawStatus as InterventionStatusFilter)
      ? (rawStatus as InterventionStatusFilter)
      : "pending_review";

  return <InterventionsPanel initialStatus={initialStatus} />;
}

export default function InterventionsPage() {
  return (
      <div className="mx-auto max-w-3xl">
      <h1 className="mb-1 text-2xl font-bold text-gray-900">Interventions</h1>
      <p className="mb-6 text-sm text-gray-500">
        Review agent-generated intervention recommendations for your students. Approve
        or dismiss each recommendation — no action is taken without your confirmation.
      </p>
      <Suspense
        fallback={
          <div aria-live="polite" aria-busy="true" className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-lg bg-gray-200" />
            ))}
          </div>
        }
      >
        <InterventionsPageContent />
      </Suspense>
    </div>
  );
}
