import type { ReactNode } from "react";

interface LegalPageShellProps {
  title: string;
  lastUpdated: string;
  version: string;
  children: ReactNode;
}

/**
 * LegalPageShell
 *
 * Shared wrapper for all legal pages that renders:
 * - The page heading
 * - "Last updated" date and document version string
 * - Print-friendly outer container (schools frequently print legal docs for IT review)
 *
 * Usage:
 *   <LegalPageShell title="Terms of Service" lastUpdated="2026-01-01" version="1.0">
 *     <AttorneyDraftBanner />
 *     ...content...
 *   </LegalPageShell>
 */
export function LegalPageShell({
  title,
  lastUpdated,
  version,
  children,
}: LegalPageShellProps) {
  return (
    <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8 print:py-4">
      <h1 className="text-4xl font-extrabold text-gray-900 print:text-3xl">
        {title}
      </h1>
      <p className="mt-2 text-sm text-gray-500">
        Last updated: {lastUpdated} &middot; Version {version}
      </p>
      <div className="mt-8 space-y-8 text-gray-700">{children}</div>
    </section>
  );
}
