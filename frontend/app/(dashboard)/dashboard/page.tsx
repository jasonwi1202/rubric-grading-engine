"use client";

/**
 * Dashboard home — teacher worklist.
 *
 * Renders the prioritized teacher worklist (M6-06).
 * The worklist shows students who need attention, ranked by urgency,
 * with mark-done / snooze / dismiss controls and filters.
 *
 * Security: no student PII in logs or query keys beyond entity IDs.
 */

import { WorklistPanel } from "@/components/worklist/WorklistPanel";

export default function DashboardPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <h1 className="mb-1 text-2xl font-bold text-gray-900">Your Worklist</h1>
      <p className="mb-6 text-sm text-gray-500">
        Prioritized actions for students who need your attention most.
      </p>
      <WorklistPanel />
    </main>
  );
}
