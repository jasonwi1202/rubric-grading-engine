"use client";

/**
 * /dashboard/copilot — Teacher Copilot dedicated page (M7-04).
 *
 * Hosts the CopilotPanel in a full-height panel layout. The copilot is
 * read-only: it surfaces information about class data but never triggers
 * grade changes or autonomous actions.
 *
 * Security: no student PII in logs or query keys beyond entity IDs.
 */

import { CopilotPanel } from "@/components/copilot/CopilotPanel";

export default function CopilotPage() {
  return (
    <main className="mx-auto flex h-[calc(100vh-4rem)] max-w-2xl flex-col px-4 py-6">
      <header className="mb-4 flex-shrink-0">
        <h1 className="text-2xl font-bold text-gray-900">Copilot</h1>
        <p className="mt-1 text-sm text-gray-500">
          Ask questions about your class data in natural language. Results link
          directly to student profiles and worklist items. No actions are taken
          on your behalf.
        </p>
      </header>

      <div className="min-h-0 flex-1">
        <CopilotPanel />
      </div>
    </main>
  );
}
