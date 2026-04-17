/**
 * AttorneyDraftBanner
 *
 * Displays a high-visibility warning banner on legal pages indicating that the
 * content has not yet been reviewed by a licensed attorney and must not be
 * treated as legal advice or relied upon in production.
 *
 * The banner is rendered unconditionally so that staging reviewers always see
 * it. Before production launch, this banner must be removed once attorney
 * review is complete and the `[ATTORNEY DRAFT REQUIRED]` placeholders in each
 * page are replaced with final legal language.
 *
 * Accessibility: uses role="alert" and aria-live="polite" so screen-reader
 * users are informed of the draft status without being interrupted.
 */
export function AttorneyDraftBanner() {
  return (
    <div
      role="alert"
      aria-live="polite"
      className="mb-8 rounded-lg border border-yellow-300 bg-yellow-50 px-4 py-4 print:hidden"
    >
      <p className="text-sm font-semibold text-yellow-800">
        ⚠ [ATTORNEY DRAFT REQUIRED] — This page contains placeholder legal
        text that has not been reviewed or approved by a licensed attorney. Do
        not rely on this content for legal compliance. Replace all placeholder
        sections before production launch.
      </p>
    </div>
  );
}
